"""Tests for hyacine.graph.fetch — mocked HTTP, no network."""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
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


def _route_graph(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[list[httpx.Request], list[float]]:
    """Send fetch.py's httpx.Client through a MockTransport.

    Returns the list every request is recorded into and the list of
    retry sleeps (the real backoff is patched out).
    """
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def recording(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    def factory(*args: Any, **kwargs: Any) -> httpx.Client:
        return _REAL_CLIENT(*args, transport=httpx.MockTransport(recording), **kwargs)

    monkeypatch.setattr("hyacine.graph.fetch.httpx.Client", factory)
    monkeypatch.setattr("hyacine.graph._http._sleep", sleeps.append)
    return requests, sleeps


def _message(msg_id: str, subject: str, folder: str = "inbox-id") -> dict[str, Any]:
    return {
        "id": msg_id,
        "subject": subject,
        "from": {"emailAddress": {"name": "Alice", "address": "alice@example.com"}},
        "receivedDateTime": "2026-10-17T01:00:00Z",
        "bodyPreview": "",
        "importance": "normal",
        "isRead": False,
        "webLink": None,
        "parentFolderId": folder,
    }


def _folder_ids(request: httpx.Request) -> httpx.Response | None:
    """Answer /me/mailFolders/{name} lookups with id "<name>-id"."""
    if "/mailFolders/" not in request.url.path:
        return None
    name = request.url.path.rsplit("/", 1)[-1]
    return httpx.Response(200, json={"id": f"{name}-id"})


_SINCE = datetime(2026, 10, 16, 0, 0, 0, tzinfo=UTC)
_UNTIL = datetime(2026, 10, 17, 0, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# test_fetch_emails_paginates
# ---------------------------------------------------------------------------

def test_fetch_emails_paginates() -> None:
    """fetch_emails should walk nextLink and return combined results with lowercased domain."""
    from hyacine.graph.fetch import fetch_emails

    page1 = {
        "value": [
            {
                "id": "msg-1",
                "subject": "Hello World",
                "from": {"emailAddress": {"name": "Alice", "address": "alice@Example.COM"}},
                "receivedDateTime": "2024-01-15T08:00:00Z",
                "bodyPreview": "preview 1",
                "importance": "normal",
                "isRead": False,
                "webLink": "https://outlook.com/1",
            }
        ],
        "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skip=1",
    }
    page2 = {
        "value": [
            {
                "id": "msg-2",
                "subject": "Second",
                "from": {"emailAddress": {"name": "Bob", "address": "BOB@University.EDU"}},
                "receivedDateTime": "2024-01-15T09:00:00Z",
                "bodyPreview": "preview 2",
                "importance": "high",
                "isRead": True,
                "webLink": None,
            }
        ],
        # No nextLink — pagination stops here
    }

    responses = [page1, page2]
    call_count = 0

    def fake_get(url: str, **kwargs: object) -> MagicMock:
        nonlocal call_count
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        if "/mailFolders/" in url:
            # Excluded-folder id lookups; not part of the message paging.
            resp.json.return_value = {"id": "folder-" + url.rsplit("/", 1)[-1]}
            return resp
        resp.json.return_value = responses[call_count]
        call_count += 1
        return resp

    cred = _make_cred()
    since = datetime(2024, 1, 15, 0, 0, 0, tzinfo=UTC)
    until = datetime(2024, 1, 16, 0, 0, 0, tzinfo=UTC)

    with patch("hyacine.graph.fetch.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = lambda s: mock_client
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = fake_get
        mock_client_cls.return_value = mock_client

        results = fetch_emails(cred, since, until)

    assert len(results) == 2

    # sender_domain must be lowercased
    assert results[0].sender_domain == "example.com"
    assert results[1].sender_domain == "university.edu"

    assert results[0].id == "msg-1"
    assert results[1].id == "msg-2"

    # Two pages means two GET calls
    assert call_count == 2


# ---------------------------------------------------------------------------
# test_fetch_calendar_sets_prefer_header
# ---------------------------------------------------------------------------

def test_fetch_calendar_sets_prefer_header() -> None:
    """fetch_calendar must send Prefer: outlook.timezone header."""
    from hyacine.graph.fetch import fetch_calendar

    empty_response = {"value": []}

    def fake_get(url: str, **kwargs: object) -> MagicMock:
        resp = MagicMock()
        resp.json.return_value = empty_response
        resp.raise_for_status.return_value = None
        return resp

    cred = _make_cred()

    with patch("hyacine.graph.fetch.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = lambda s: mock_client
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = fake_get
        mock_client_cls.return_value = mock_client

        result = fetch_calendar(cred, date(2024, 1, 15), timezone_name="Asia/Singapore")

    assert result == []

    # Inspect the headers kwarg passed to .get()
    call_kwargs = mock_client.get.call_args
    headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
    prefer = headers.get("Prefer", "")
    assert "outlook.timezone" in prefer
    assert "Singapore Standard Time" in prefer


# ---------------------------------------------------------------------------
# fetch_calendar — local-day window, zone-aware parsing, paging
# ---------------------------------------------------------------------------

def test_fetch_calendar_window_is_local_day_as_utc_instants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Asia/Singapore 2026-10-17 is 2026-10-16T16:00Z .. 2026-10-17T16:00Z."""
    from hyacine.graph.fetch import fetch_calendar

    requests, _ = _route_graph(monkeypatch, lambda r: httpx.Response(200, json={"value": []}))

    fetch_calendar(_make_cred(), date(2026, 10, 17), timezone_name="Asia/Singapore")

    assert len(requests) == 1
    params = requests[0].url.params
    assert params["startDateTime"] == "2026-10-16T16:00:00Z"
    assert params["endDateTime"] == "2026-10-17T16:00:00Z"
    assert params["$top"] == "100"
    assert params["$orderby"] == "start/dateTime"


def test_fetch_calendar_unknown_zone_falls_back_to_utc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unknown zone uses the UTC day for the window and the Prefer header."""
    from hyacine.graph.fetch import fetch_calendar

    requests, _ = _route_graph(monkeypatch, lambda r: httpx.Response(200, json={"value": []}))

    fetch_calendar(_make_cred(), date(2026, 10, 17), timezone_name="Not/AZone")

    params = requests[0].url.params
    assert params["startDateTime"] == "2026-10-17T00:00:00Z"
    assert params["endDateTime"] == "2026-10-18T00:00:00Z"
    assert requests[0].headers["Prefer"] == 'outlook.timezone="UTC"'


def test_fetch_calendar_attaches_requested_zone_to_naive_times(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Graph's naive SGT wall-clock times must serialize as +08:00, not as UTC."""
    from hyacine.graph.fetch import fetch_calendar
    from hyacine.models import CalendarEvent

    events = [
        {
            "id": "ev-sgt",
            "subject": "Standup",
            "start": {"dateTime": "2026-10-17T09:00:00.0000000", "timeZone": "Singapore Standard Time"},
            "end": {"dateTime": "2026-10-17T09:30:00.0000000", "timeZone": "Singapore Standard Time"},
        },
        {
            # Prefer not applied: Graph labels the value as UTC.
            "id": "ev-utc",
            "subject": "Sync",
            "start": {"dateTime": "2026-10-17T01:00:00.0000000", "timeZone": "UTC"},
            "end": {"dateTime": "2026-10-17T02:00:00.0000000", "timeZone": "UTC"},
        },
    ]
    _route_graph(monkeypatch, lambda r: httpx.Response(200, json={"value": events}))

    result = fetch_calendar(_make_cred(), date(2026, 10, 17), timezone_name="Asia/Singapore")

    sgt, utc = result
    assert sgt.start.isoformat() == "2026-10-17T09:00:00+08:00"
    assert '"start":"2026-10-17T09:00:00+08:00"' in sgt.model_dump_json()
    assert '"end":"2026-10-17T09:30:00+08:00"' in sgt.model_dump_json()
    # Both events describe the same instant (09:00 SGT == 01:00 UTC).
    assert utc.start == datetime(2026, 10, 17, 1, 0, tzinfo=UTC)
    assert utc.start == sgt.start
    assert isinstance(sgt, CalendarEvent)


def test_fetch_calendar_follows_next_link_with_prefer_on_every_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """calendarView pages at 10 by default; every page must be fetched with Prefer."""
    from hyacine.graph.fetch import fetch_calendar

    next_link = "https://graph.microsoft.com/v1.0/me/calendarView?$skiptoken=page2"
    tz = {"timeZone": "Singapore Standard Time"}

    def handler(request: httpx.Request) -> httpx.Response:
        if "skiptoken" in str(request.url):
            return httpx.Response(200, json={"value": [
                {"id": "ev-2", "start": {"dateTime": "2026-10-17T14:00:00", **tz},
                 "end": {"dateTime": "2026-10-17T15:00:00", **tz}},
            ]})
        return httpx.Response(200, json={
            "value": [
                {"id": "ev-1", "start": {"dateTime": "2026-10-17T09:00:00", **tz},
                 "end": {"dateTime": "2026-10-17T10:00:00", **tz}},
            ],
            "@odata.nextLink": next_link,
        })

    requests, _ = _route_graph(monkeypatch, handler)

    result = fetch_calendar(_make_cred(), date(2026, 10, 17), timezone_name="Asia/Singapore")

    assert [ev.id for ev in result] == ["ev-1", "ev-2"]
    assert len(requests) == 2
    assert str(requests[1].url) == next_link
    for req in requests:
        assert req.headers["Prefer"] == 'outlook.timezone="Singapore Standard Time"'


# ---------------------------------------------------------------------------
# fetch_emails — folder exclusion, own-digest skip, retry, errors, page cap
# ---------------------------------------------------------------------------

def test_fetch_emails_skips_excluded_folders_and_own_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sent/Drafts/Deleted/Junk/Outbox and Hyacine's own digest never reach the LLM."""
    from hyacine.graph.fetch import fetch_emails

    messages = [
        _message("keep-inbox", "Quarterly review"),
        _message("sent", "My reply", folder="sentitems-id"),
        _message("draft", "Unsent", folder="drafts-id"),
        _message("trash", "Old", folder="deleteditems-id"),
        _message("junk", "WIN A PRIZE", folder="junkemail-id"),
        _message("outbox", "Queued", folder="outbox-id"),
        _message("digest", "Hyacine · 2026-10-16"),
        _message("digest-archived", "Hyacine · 2026-10-15", folder="archive-id"),
        _message("preview", "Hyacine · 2026-10-16 (preview)"),
        _message("keep-reply", "Re: Hyacine · 2026-10-16"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return _folder_ids(request) or httpx.Response(200, json={"value": messages})

    requests, _ = _route_graph(monkeypatch, handler)

    result = fetch_emails(_make_cred(), _SINCE, _UNTIL)

    assert [m.id for m in result] == ["keep-inbox", "keep-reply"]
    looked_up = {r.url.path.rsplit("/", 1)[-1] for r in requests if "/mailFolders/" in r.url.path}
    assert looked_up == {"sentitems", "drafts", "deleteditems", "junkemail", "outbox"}
    messages_req = next(r for r in requests if r.url.path.endswith("/me/messages"))
    assert "parentFolderId" in messages_req.url.params["$select"].split(",")


def test_fetch_emails_survives_failed_folder_lookups(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """A folder that can't be resolved is simply not excluded; the run goes on."""
    from hyacine.graph.fetch import fetch_emails

    messages = [
        _message("in-drafts", "Unsent", folder="drafts-id"),
        _message("in-sent", "Reply", folder="sentitems-id"),
        _message("in-junk", "Spam", folder="junkemail-id"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/mailFolders/drafts"):
            raise httpx.ConnectError("boom", request=request)
        if path.endswith("/mailFolders/sentitems"):
            return httpx.Response(404, json={"error": {"code": "ErrorItemNotFound"}})
        if path.endswith("/mailFolders/outbox"):
            return httpx.Response(200, text="not json")
        return _folder_ids(request) or httpx.Response(200, json={"value": messages})

    _route_graph(monkeypatch, handler)

    with caplog.at_level(logging.WARNING, logger="hyacine.graph.fetch"):
        result = fetch_emails(_make_cred(), _SINCE, _UNTIL)

    # drafts / sentitems unresolved → kept; junkemail resolved → skipped.
    assert [m.id for m in result] == ["in-drafts", "in-sent"]
    warned = " ".join(r.getMessage() for r in caplog.records)
    assert "'drafts'" in warned and "'sentitems'" in warned and "'outbox'" in warned


def test_fetch_emails_retries_transient_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 503 on a message page is retried and the run still succeeds."""
    from hyacine.graph.fetch import fetch_emails

    page_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal page_calls
        if (folder := _folder_ids(request)) is not None:
            return folder
        page_calls += 1
        if page_calls == 1:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json={"value": [_message("m1", "Hi")]})

    _, sleeps = _route_graph(monkeypatch, handler)

    result = fetch_emails(_make_cred(), _SINCE, _UNTIL)

    assert [m.id for m in result] == ["m1"]
    assert page_calls == 2
    assert sleeps == [2.0]


def test_fetch_emails_error_includes_graph_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 4xx surfaces Graph's error body, still as an httpx.HTTPStatusError."""
    from hyacine.graph.fetch import fetch_emails

    body = '{"error":{"code":"BadRequest","message":"Invalid filter clause"}}'

    def handler(request: httpx.Request) -> httpx.Response:
        return _folder_ids(request) or httpx.Response(400, text=body)

    _, sleeps = _route_graph(monkeypatch, handler)

    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        fetch_emails(_make_cred(), _SINCE, _UNTIL)

    assert "Invalid filter clause" in str(excinfo.value)
    assert "400" in str(excinfo.value)
    assert sleeps == []  # 400 is not transient


def test_fetch_emails_warns_when_page_cap_hit(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """Hitting max_pages with nextLink still set must be visible in the log."""
    from hyacine.graph.fetch import FetchedEmails, fetch_emails

    def handler(request: httpx.Request) -> httpx.Response:
        return _folder_ids(request) or httpx.Response(200, json={
            "value": [_message("m1", "Hi"), _message("m2", "Yo")],
            "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skip=2",
        })

    _route_graph(monkeypatch, handler)

    with caplog.at_level(logging.WARNING, logger="hyacine.graph.fetch"):
        result = fetch_emails(_make_cred(), _SINCE, _UNTIL, max_pages=1)

    assert len(result) == 2
    # run.py reads this to say "at least N" older emails were left out.
    assert isinstance(result, FetchedEmails)
    assert result.page_cap_hit is True
    [record] = [r for r in caplog.records if "page cap" in r.getMessage()]
    message = record.getMessage()
    assert "1-page cap" in message
    assert "kept 2 of 2" in message
    assert "2026-10-16T00:00:00Z..2026-10-17T00:00:00Z" in message


def test_fetch_emails_no_page_cap_warning_when_exhausted(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """No warning when the last page has no nextLink."""
    from hyacine.graph.fetch import FetchedEmails, fetch_emails

    def handler(request: httpx.Request) -> httpx.Response:
        return _folder_ids(request) or httpx.Response(200, json={"value": [_message("m1", "Hi")]})

    _route_graph(monkeypatch, handler)

    with caplog.at_level(logging.WARNING, logger="hyacine.graph.fetch"):
        result = fetch_emails(_make_cred(), _SINCE, _UNTIL, max_pages=1)

    assert not [r for r in caplog.records if "page cap" in r.getMessage()]
    assert isinstance(result, FetchedEmails)
    assert result.page_cap_hit is False
