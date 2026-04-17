"""Three-channel monitoring.

1. Error email via /me/sendMail — primary signal, reuses the pipeline's
   authenticated credential.
2. ntfy.sh — independent channel for "email path itself is broken".
3. healthchecks.io — external dead-man's switch; catches "daemon never ran".
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import httpx
from azure.identity import DeviceCodeCredential

HcEvent = Literal["start", "success", "fail"]

_HC_BASE = "https://hc-ping.com"
_NTFY_BASE = "https://ntfy.sh"
_MAX_PAYLOAD_BYTES = 10 * 1024  # 10 KB


def ping_healthchecks(
    uuid: str,
    event: HcEvent,
    payload: str = "",
    *,
    client: httpx.Client | None = None,
) -> bool:
    """POST to hc-ping.com/<uuid>[/start|/fail]; body is traceback on fail.

    Truncates payload to 10 KB. Returns True on HTTP 2xx. Never raises —
    monitoring paths must not escalate their own failures.
    """
    if not uuid:
        return False

    suffix = {"start": "/start", "fail": "/fail", "success": ""}[event]
    url = f"{_HC_BASE}/{uuid}{suffix}"

    owned = client is None
    _client = client or httpx.Client(timeout=10.0)
    try:
        if payload:
            body = payload.encode()[:_MAX_PAYLOAD_BYTES]
            resp = _client.post(url, content=body)
        else:
            resp = _client.get(url)
        return resp.is_success
    except (httpx.HTTPError, Exception):
        return False
    finally:
        if owned:
            _client.close()


def send_ntfy(
    topic: str,
    message: str,
    *,
    title: str = "hyacine",
    priority: int = 4,
    client: httpx.Client | None = None,
) -> bool:
    """POST to ntfy.sh/<topic>. Returns True on success. Never raises."""
    if not topic:
        return False

    url = f"{_NTFY_BASE}/{topic}"
    headers = {"Title": title, "Priority": str(priority)}

    owned = client is None
    _client = client or httpx.Client(timeout=10.0)
    try:
        resp = _client.post(url, content=message.encode(), headers=headers)
        return resp.is_success
    except (httpx.HTTPError, Exception):
        return False
    finally:
        if owned:
            _client.close()


def send_error_email(
    cred: DeviceCodeCredential,
    recipient: str,
    subject_suffix: str,
    traceback_text: str,
) -> bool:
    """Reuse graph.send with a [BRIEFING ERROR] prefix. Never raises."""
    try:
        from hyacine.graph.send import send_briefing_email  # lazy import

        now_utc = datetime.now(UTC).isoformat(timespec="seconds")
        subject = f"[BRIEFING ERROR] {subject_suffix}"
        markdown_body = f"**Error timestamp (UTC):** {now_utc}\n\n```\n{traceback_text}\n```\n"
        send_briefing_email(cred, recipient, subject, markdown_body)
        return True
    except Exception:
        return False


__all__ = ["ping_healthchecks", "send_ntfy", "send_error_email", "HcEvent"]
