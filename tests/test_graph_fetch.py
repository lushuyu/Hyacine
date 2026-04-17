"""Tests for hyacine.graph.fetch — mocked HTTP, no network."""
from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch


def _make_cred() -> MagicMock:
    cred = MagicMock()
    token = MagicMock()
    token.token = "fake-token"
    cred.get_token.return_value = token
    return cred


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
        resp.json.return_value = responses[call_count]
        resp.raise_for_status.return_value = None
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
