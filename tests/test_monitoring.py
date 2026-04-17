"""Tests for src/hyacine/ops/monitoring.py.

All httpx calls are mocked — no real network.
"""
from __future__ import annotations

import pathlib
import sys
from unittest.mock import MagicMock, patch

import httpx

# Ensure src is on path (pytest.ini_options.pythonpath handles this, but be explicit)
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

from hyacine.ops.monitoring import ping_healthchecks, send_error_email, send_ntfy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SYSTEMD_DIR = pathlib.Path(__file__).parent.parent / "src" / "hyacine" / "ops" / "systemd"


def _make_response(status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.is_success = 200 <= status_code < 300
    return resp


# ---------------------------------------------------------------------------
# ping_healthchecks
# ---------------------------------------------------------------------------


def test_ping_healthchecks_success() -> None:
    """200 response → True."""
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.return_value = _make_response(200)
    result = ping_healthchecks("test-uuid-1234", "success", client=mock_client)
    assert result is True
    mock_client.get.assert_called_once()


def test_ping_healthchecks_start_uses_start_suffix() -> None:
    """event='start' → URL ends with /start."""
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.return_value = _make_response(200)
    ping_healthchecks("abc-uuid", "start", client=mock_client)
    url_called = mock_client.get.call_args[0][0]
    assert url_called.endswith("/start")


def test_ping_healthchecks_fail_uses_fail_suffix() -> None:
    """event='fail' → URL ends with /fail."""
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.return_value = _make_response(200)
    ping_healthchecks("abc-uuid", "fail", client=mock_client)
    url_called = mock_client.get.call_args[0][0]
    assert url_called.endswith("/fail")


def test_ping_healthchecks_fail_swallowed() -> None:
    """ConnectError must not propagate — returns False instead."""
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.side_effect = httpx.ConnectError("refused")
    result = ping_healthchecks("test-uuid", "success", client=mock_client)
    assert result is False


def test_ping_healthchecks_non2xx_returns_false() -> None:
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.return_value = _make_response(500)
    assert ping_healthchecks("test-uuid", "success", client=mock_client) is False


def test_ping_healthchecks_truncates_large_payload() -> None:
    """20 KB payload must be truncated to ≤ 10 KB before sending."""
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _make_response(200)

    large_payload = "x" * (20 * 1024)
    result = ping_healthchecks("test-uuid", "fail", large_payload, client=mock_client)

    assert result is True
    call_kwargs = mock_client.post.call_args
    # content keyword or positional — check content kwarg
    sent_body: bytes = call_kwargs[1].get("content") or call_kwargs[0][1]
    assert len(sent_body) <= 10 * 1024


def test_ping_healthchecks_empty_uuid_returns_false() -> None:
    mock_client = MagicMock(spec=httpx.Client)
    result = ping_healthchecks("", "success", client=mock_client)
    assert result is False
    mock_client.get.assert_not_called()
    mock_client.post.assert_not_called()


def test_ping_healthchecks_closes_owned_client() -> None:
    """When no client is passed, the function must close the one it creates."""
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.return_value = _make_response(200)
    with patch("hyacine.ops.monitoring.httpx.Client", return_value=mock_client):
        ping_healthchecks("uuid-xyz", "success")
    mock_client.close.assert_called_once()


# ---------------------------------------------------------------------------
# send_ntfy
# ---------------------------------------------------------------------------


def test_send_ntfy_success() -> None:
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _make_response(200)
    result = send_ntfy("my-topic", "hello world", client=mock_client)
    assert result is True
    mock_client.post.assert_called_once()


def test_send_ntfy_swallows_errors() -> None:
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.side_effect = httpx.TimeoutException("timed out")
    result = send_ntfy("my-topic", "hello", client=mock_client)
    assert result is False


def test_send_ntfy_empty_topic() -> None:
    mock_client = MagicMock(spec=httpx.Client)
    result = send_ntfy("", "hello", client=mock_client)
    assert result is False
    mock_client.post.assert_not_called()


def test_send_ntfy_sends_title_priority_headers() -> None:
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _make_response(200)
    send_ntfy("topic", "msg", title="my-title", priority=5, client=mock_client)
    headers_sent = mock_client.post.call_args[1]["headers"]
    assert headers_sent["Title"] == "my-title"
    assert headers_sent["Priority"] == "5"


def test_send_ntfy_non2xx_returns_false() -> None:
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = _make_response(503)
    assert send_ntfy("topic", "msg", client=mock_client) is False


# ---------------------------------------------------------------------------
# send_error_email
# ---------------------------------------------------------------------------


def test_send_error_email_swallows_graph_failure() -> None:
    """If send_email raises, send_error_email returns False — no propagation."""

    fake_cred = MagicMock()
    with patch(
        "hyacine.graph.send.send_email",
        side_effect=RuntimeError("graph down"),
    ):
        result = send_error_email(fake_cred, "lu@example.com", "pipeline crashed", "Traceback...")
    assert result is False


def test_send_error_email_calls_with_expected_subject() -> None:
    """Subject must start with [HYACINE ERROR]."""
    fake_cred = MagicMock()
    recorded: dict[str, object] = {}

    def capture(cred, recipient, subject, markdown_body, **kwargs):  # type: ignore[override]
        recorded["subject"] = subject
        recorded["body"] = markdown_body
        return "msg-id-001"

    with patch("hyacine.graph.send.send_email", side_effect=capture):
        result = send_error_email(
            fake_cred, "lu@example.com", "daily run failed", "Traceback (most recent call last)..."
        )

    assert result is True
    assert str(recorded["subject"]).startswith("[HYACINE ERROR]")


def test_send_error_email_body_contains_pre_block() -> None:
    """Traceback must be wrapped in a code/pre block (markdown fenced code)."""
    fake_cred = MagicMock()
    recorded: dict[str, object] = {}

    def capture(cred, recipient, subject, markdown_body, **kwargs):  # type: ignore[override]
        recorded["body"] = markdown_body
        return "id"

    with patch("hyacine.graph.send.send_email", side_effect=capture):
        send_error_email(fake_cred, "alice@example.com", "boom", "some traceback text")

    body = str(recorded["body"])
    assert "some traceback text" in body
    # Markdown fenced code block (``` markers)
    assert "```" in body


def test_send_error_email_body_contains_utc_timestamp() -> None:
    """Body must include an ISO UTC timestamp line."""
    fake_cred = MagicMock()
    recorded: dict[str, object] = {}

    def capture(cred, recipient, subject, markdown_body, **kwargs):  # type: ignore[override]
        recorded["body"] = markdown_body
        return "id"

    with patch("hyacine.graph.send.send_email", side_effect=capture):
        send_error_email(fake_cred, "alice@example.com", "oops", "tb")

    body = str(recorded["body"])
    # ISO UTC format includes +00:00 or Z
    assert "+00:00" in body or "UTC" in body or "Z" in body


# ---------------------------------------------------------------------------
# systemd unit file content validation
# ---------------------------------------------------------------------------

_REQUIRED_SERVICE_DIRECTIVES = [
    "UnsetEnvironment=ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN",
    "EnvironmentFile=%h/hyacine/.env",
    "WorkingDirectory=%h/hyacine",
    # ReadWritePaths must cover our repo state AND MSAL's non-relocatable
    # token cache at ~/.IdentityService/. Split assertions keep the test
    # robust if the ordering or spacing of the directive changes.
    "ReadWritePaths=",
    "%h/hyacine/data",
    "%h/hyacine/prompts",
    "%h/hyacine/config",
    "%h/.IdentityService",
    "NoNewPrivileges=true",
    "PrivateTmp=true",
    "ProtectSystem=strict",
    "ProtectHome=read-only",
    "RestrictAddressFamilies",
    "RestrictNamespaces=true",
    "LockPersonality=true",
    "MemoryDenyWriteExecute=true",
    "SystemCallArchitectures=native",
]

_REQUIRED_TIMER_DIRECTIVES = [
    "OnCalendar=*-*-* 07:30:00",
    "Persistent=true",
    "RandomizedDelaySec=2min",
]


def test_systemd_units_have_required_directives() -> None:
    """All .service and .timer files must contain the required directives."""
    service_files = list(_SYSTEMD_DIR.glob("*.service"))
    timer_files = list(_SYSTEMD_DIR.glob("*.timer"))

    assert service_files, f"No .service files found in {_SYSTEMD_DIR}"
    assert timer_files, f"No .timer files found in {_SYSTEMD_DIR}"

    for svc in service_files:
        content = svc.read_text()
        for directive in _REQUIRED_SERVICE_DIRECTIVES:
            assert directive in content, (
                f"{svc.name} missing directive: {directive!r}"
            )

    for tmr in timer_files:
        content = tmr.read_text()
        for directive in _REQUIRED_TIMER_DIRECTIVES:
            assert directive in content, (
                f"{tmr.name} missing directive: {directive!r}"
            )
