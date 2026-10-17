"""Tests for hyacine.graph.send — mocked HTTP, no network."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

_REAL_CLIENT = httpx.Client


def _make_cred() -> MagicMock:
    cred = MagicMock()
    token = MagicMock()
    token.token = "fake-token"
    cred.get_token.return_value = token
    return cred


def _route_sendmail(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[list[httpx.Request], list[float]]:
    """Send send.py's httpx.Client through a MockTransport; no real backoff."""
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def recording(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    def factory(*args: Any, **kwargs: Any) -> httpx.Client:
        return _REAL_CLIENT(*args, transport=httpx.MockTransport(recording), **kwargs)

    monkeypatch.setattr("hyacine.graph.send.httpx.Client", factory)
    monkeypatch.setattr("hyacine.graph._http._sleep", sleeps.append)
    return requests, sleeps


# ---------------------------------------------------------------------------
# test_render_html_body_escapes_script_tag
# ---------------------------------------------------------------------------

def test_render_html_body_escapes_script_tag() -> None:
    """Script tags must be stripped by bleach.clean — XSS prevention."""
    from hyacine.graph.send import render_html_body

    html = render_html_body("Hello\n\n<script>alert(1)</script>\n\nWorld")
    assert "<script>" not in html
    assert "alert(1)" not in html


# ---------------------------------------------------------------------------
# test_send_email_posts_expected_body
# ---------------------------------------------------------------------------

def test_send_email_posts_expected_body() -> None:
    """send_email should POST correctly shaped JSON to /me/sendMail."""
    from hyacine.graph.send import send_email

    captured_payload: dict = {}
    captured_url: str = ""

    def fake_post(url: str, **kwargs: object) -> MagicMock:
        nonlocal captured_payload, captured_url
        captured_url = url
        captured_payload = kwargs.get("json", {})  # type: ignore[assignment]
        resp = MagicMock()
        resp.is_success = True
        resp.headers = {"request-id": "test-request-id-123"}
        return resp

    cred = _make_cred()

    with patch("hyacine.graph.send.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = lambda s: mock_client
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = fake_post
        mock_client_cls.return_value = mock_client

        result = send_email(
            cred,
            recipient="test@example.com",
            subject="Test Subject",
            markdown_body="**Hello** world",
            save_to_sent_items=True,
        )

    # Verify URL
    assert "/me/sendMail" in captured_url

    # Verify payload shape
    message = captured_payload.get("message", {})
    assert message.get("subject") == "Test Subject"

    body = message.get("body", {})
    assert body.get("contentType") == "HTML"
    content = body.get("content", "")
    # Markdown bold round-trips through bleach into a styled <strong> tag
    # — accept any inline-styled variant the modern shell emits.
    assert "<strong" in content
    assert "Hello" in content
    # Modern shell signatures: doctype + the HyacineAI footer signature.
    assert "<!doctype html>" in content
    assert "HyacineAI" in content

    recipients = message.get("toRecipients", [])
    assert len(recipients) == 1
    assert recipients[0]["emailAddress"]["address"] == "test@example.com"

    assert captured_payload.get("saveToSentItems") is True

    # Verify returned id comes from request-id header
    assert result == "test-request-id-123"


def test_send_email_synthetic_id_when_no_header() -> None:
    """When request-id header is absent, a synthetic uuid is returned."""
    from hyacine.graph.send import send_email

    def fake_post(url: str, **kwargs: object) -> MagicMock:
        resp = MagicMock()
        resp.is_success = True
        resp.headers = {}
        return resp

    cred = _make_cred()

    with patch("hyacine.graph.send.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = lambda s: mock_client
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = fake_post
        mock_client_cls.return_value = mock_client

        result = send_email(cred, "r@x.com", "s", "body")

    assert result.startswith("sendmail-")


def test_send_email_raises_on_non_2xx() -> None:
    """RuntimeError should be raised when Graph returns a non-2xx status."""
    from hyacine.graph.send import send_email

    def fake_post(url: str, **kwargs: object) -> MagicMock:
        resp = MagicMock()
        resp.is_success = False
        resp.status_code = 403
        resp.text = "Forbidden"
        return resp

    cred = _make_cred()

    with patch("hyacine.graph.send.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = lambda s: mock_client
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = fake_post
        mock_client_cls.return_value = mock_client

        import pytest
        with pytest.raises(RuntimeError, match="403"):
            send_email(cred, "r@x.com", "s", "body")


# ---------------------------------------------------------------------------
# sendMail retry policy — never risk a duplicate digest
# ---------------------------------------------------------------------------

def test_send_email_not_retried_on_read_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ReadTimeout may mean Graph already accepted the mail: surface it, once."""
    from hyacine.graph.send import send_email

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no response", request=request)

    requests, sleeps = _route_sendmail(monkeypatch, handler)

    with pytest.raises(httpx.ReadTimeout):
        send_email(_make_cred(), "r@x.com", "s", "body")

    assert len(requests) == 1
    assert sleeps == []


def test_send_email_not_retried_on_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """500 is ambiguous for a non-idempotent POST; raise with Graph's body, no retry."""
    from hyacine.graph._http import GraphHTTPError
    from hyacine.graph.send import send_email

    body = '{"error":{"code":"ErrorInternalServerError","message":"try later"}}'
    requests, _ = _route_sendmail(monkeypatch, lambda r: httpx.Response(500, text=body))

    with pytest.raises(GraphHTTPError) as excinfo:
        send_email(_make_cred(), "r@x.com", "s", "body")

    assert len(requests) == 1
    assert "500" in str(excinfo.value)
    assert "ErrorInternalServerError" in str(excinfo.value)
    assert isinstance(excinfo.value, RuntimeError)


def test_send_email_retries_throttled_post(monkeypatch: pytest.MonkeyPatch) -> None:
    """429 means Graph refused the request, so resending is safe."""
    from hyacine.graph.send import send_email

    responses = iter([
        httpx.Response(429, headers={"Retry-After": "4"}),
        httpx.Response(202, headers={"request-id": "rid-after-retry"}),
    ])
    requests, sleeps = _route_sendmail(monkeypatch, lambda r: next(responses))

    result = send_email(_make_cred(), "r@x.com", "s", "body")

    assert result == "rid-after-retry"
    assert len(requests) == 2
    assert sleeps == [4]
    assert requests[0].content == requests[1].content

