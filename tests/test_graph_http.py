"""Tests for hyacine.graph._http — retry policy and Graph error messages."""
from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from hyacine.graph import _http
from hyacine.graph._http import GraphHTTPError, raise_for_graph_status, request_with_retry

_URL = "https://graph.microsoft.com/v1.0/me/messages"
_SEND_URL = "https://graph.microsoft.com/v1.0/me/sendMail"

Outcome = httpx.Response | type[httpx.TransportError]


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record backoff sleeps instead of actually sleeping."""
    recorded: list[float] = []
    monkeypatch.setattr(_http, "_sleep", recorded.append)
    return recorded


def _scripted(outcomes: list[Outcome]) -> tuple[httpx.Client, list[httpx.Request]]:
    """Client whose transport plays ``outcomes`` in order (response or error class)."""
    seen: list[httpx.Request] = []
    queue: Iterator[Outcome] = iter(outcomes)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        outcome = next(queue)
        if isinstance(outcome, httpx.Response):
            return outcome
        raise outcome("scripted failure", request=request)

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def _ok() -> httpx.Response:
    return httpx.Response(200, json={"value": []})


# ---------------------------------------------------------------------------
# GET (idempotent)
# ---------------------------------------------------------------------------

def test_get_honours_retry_after_on_429(sleeps: list[float]) -> None:
    client, seen = _scripted([httpx.Response(429, headers={"Retry-After": "7"}), _ok()])

    resp = request_with_retry(client, "GET", _URL)

    assert resp.status_code == 200
    assert len(seen) == 2
    assert sleeps == [7]


def test_retry_after_is_capped(sleeps: list[float]) -> None:
    client, _ = _scripted([httpx.Response(429, headers={"Retry-After": "3600"}), _ok()])

    request_with_retry(client, "GET", _URL)

    assert sleeps == [60]


def test_unparseable_retry_after_uses_backoff(sleeps: list[float]) -> None:
    client, _ = _scripted([
        httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),
        _ok(),
    ])

    request_with_retry(client, "GET", _URL)

    assert sleeps == [2.0]


def test_get_retries_503_then_succeeds(sleeps: list[float]) -> None:
    client, seen = _scripted([httpx.Response(503), _ok()])

    resp = request_with_retry(client, "GET", _URL)

    assert resp.status_code == 200
    assert len(seen) == 2
    assert sleeps == [2.0]


def test_get_gives_up_after_three_attempts(sleeps: list[float]) -> None:
    """The last error response is returned for raise_for_graph_status to report."""
    client, seen = _scripted([httpx.Response(502), httpx.Response(500), httpx.Response(504)])

    resp = request_with_retry(client, "GET", _URL)

    assert resp.status_code == 504
    assert len(seen) == 3
    assert sleeps == [2.0, 5.0]


def test_get_retries_transport_errors(sleeps: list[float]) -> None:
    client, seen = _scripted([httpx.ReadTimeout, httpx.ConnectError, _ok()])

    resp = request_with_retry(client, "GET", _URL)

    assert resp.status_code == 200
    assert len(seen) == 3


def test_get_reraises_last_transport_error(sleeps: list[float]) -> None:
    client, seen = _scripted([httpx.ReadTimeout, httpx.ReadTimeout, httpx.ReadTimeout])

    with pytest.raises(httpx.ReadTimeout):
        request_with_retry(client, "GET", _URL)

    assert len(seen) == 3


def test_get_does_not_retry_client_errors(sleeps: list[float]) -> None:
    client, seen = _scripted([httpx.Response(404)])

    resp = request_with_retry(client, "GET", _URL)

    assert resp.status_code == 404
    assert len(seen) == 1
    assert sleeps == []


# ---------------------------------------------------------------------------
# POST (sendMail — not idempotent)
# ---------------------------------------------------------------------------

def test_post_not_retried_on_read_timeout(sleeps: list[float]) -> None:
    """Graph may already have the mail; retrying would send it twice."""
    client, seen = _scripted([httpx.ReadTimeout, _ok()])

    with pytest.raises(httpx.ReadTimeout):
        request_with_retry(client, "POST", _SEND_URL, json={})

    assert len(seen) == 1
    assert sleeps == []


@pytest.mark.parametrize("status", [500, 502, 504])
def test_post_not_retried_on_ambiguous_5xx(status: int, sleeps: list[float]) -> None:
    client, seen = _scripted([httpx.Response(status), _ok()])

    resp = request_with_retry(client, "POST", _SEND_URL, json={})

    assert resp.status_code == status
    assert len(seen) == 1


@pytest.mark.parametrize("status", [429, 503])
def test_post_retried_when_graph_refused(status: int, sleeps: list[float]) -> None:
    client, seen = _scripted([httpx.Response(status), httpx.Response(202)])

    resp = request_with_retry(client, "POST", _SEND_URL, json={})

    assert resp.status_code == 202
    assert len(seen) == 2


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout])
def test_post_retried_when_request_never_left(
    error: type[httpx.TransportError], sleeps: list[float],
) -> None:
    client, seen = _scripted([error, httpx.Response(202)])

    resp = request_with_retry(client, "POST", _SEND_URL, json={})

    assert resp.status_code == 202
    assert len(seen) == 2


def test_post_resends_same_body(sleeps: list[float]) -> None:
    client, seen = _scripted([httpx.Response(429), httpx.Response(202)])

    request_with_retry(client, "POST", _SEND_URL, json={"message": {"subject": "s"}})

    assert seen[0].content == seen[1].content == b'{"message":{"subject":"s"}}'


# ---------------------------------------------------------------------------
# raise_for_graph_status
# ---------------------------------------------------------------------------

def _response(status: int, text: str) -> httpx.Response:
    return httpx.Response(status, text=text, request=httpx.Request("GET", _URL + "?$top=100"))


def test_error_message_carries_graph_body() -> None:
    body = '{"error":{"code":"ErrorAccessDenied","message":"Access is denied."}}'

    with pytest.raises(GraphHTTPError) as excinfo:
        raise_for_graph_status(_response(403, body))

    message = str(excinfo.value)
    assert "403" in message
    assert "Access is denied." in message
    assert "GET https://graph.microsoft.com/v1.0/me/messages" in message
    assert "$top" not in message  # query string left out
    assert excinfo.value.response.status_code == 403


def test_error_is_http_status_error_and_runtime_error() -> None:
    """Existing ``except httpx.HTTPStatusError`` / ``except RuntimeError`` keep working."""
    with pytest.raises(httpx.HTTPStatusError):
        raise_for_graph_status(_response(500, "x"))
    with pytest.raises(RuntimeError):
        raise_for_graph_status(_response(500, "x"))


def test_error_body_is_truncated() -> None:
    with pytest.raises(GraphHTTPError) as excinfo:
        raise_for_graph_status(_response(400, "a" * 2000))

    assert "a" * 500 in str(excinfo.value)
    assert "a" * 501 not in str(excinfo.value)


def test_empty_error_body_is_labelled() -> None:
    with pytest.raises(GraphHTTPError, match="<empty body>"):
        raise_for_graph_status(_response(401, ""))


@pytest.mark.parametrize("status", [200, 202, 204])
def test_success_does_not_raise(status: int) -> None:
    raise_for_graph_status(_response(status, ""))


def test_retry_then_raise_reports_last_response(sleeps: list[float]) -> None:
    """End to end: exhausted retries surface the final status and body."""
    client, _ = _scripted([
        httpx.Response(503, text="busy"),
        httpx.Response(503, text="busy"),
        httpx.Response(503, text="still busy"),
    ])

    with pytest.raises(GraphHTTPError, match="503: still busy"):
        raise_for_graph_status(request_with_retry(client, "GET", _URL))
