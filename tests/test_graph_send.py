"""Tests for hyacine.graph.send — mocked HTTP, no network."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_cred() -> MagicMock:
    cred = MagicMock()
    token = MagicMock()
    token.token = "fake-token"
    cred.get_token.return_value = token
    return cred


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
# test_send_briefing_email_posts_expected_body
# ---------------------------------------------------------------------------

def test_send_briefing_email_posts_expected_body() -> None:
    """send_briefing_email should POST correctly shaped JSON to /me/sendMail."""
    from hyacine.graph.send import send_briefing_email

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

        result = send_briefing_email(
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
    assert "<strong>Hello</strong>" in body.get("content", "")

    recipients = message.get("toRecipients", [])
    assert len(recipients) == 1
    assert recipients[0]["emailAddress"]["address"] == "test@example.com"

    assert captured_payload.get("saveToSentItems") is True

    # Verify returned id comes from request-id header
    assert result == "test-request-id-123"


def test_send_briefing_email_synthetic_id_when_no_header() -> None:
    """When request-id header is absent, a synthetic uuid is returned."""
    from hyacine.graph.send import send_briefing_email

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

        result = send_briefing_email(cred, "r@x.com", "s", "body")

    assert result.startswith("sendmail-")


def test_send_briefing_email_raises_on_non_2xx() -> None:
    """RuntimeError should be raised when Graph returns a non-2xx status."""
    from hyacine.graph.send import send_briefing_email

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
            send_briefing_email(cred, "r@x.com", "s", "body")
