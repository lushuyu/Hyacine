"""Microsoft Graph device-code OAuth handlers.

The flow is split across three calls so the webview can animate polling:

  1. `graph.start_device_flow`  → returns user_code + verification_uri;
                                   spawns a background poll that emits
                                   `graph.device_flow` events until approval,
                                   expiry, or cancellation.
  2. `graph.cancel_device_flow` → client aborts before approval.
  3. `graph.me`                 → once a record exists, fetch profile for the
                                   "signed in as" badge.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import httpx

from hyacine.config import get_settings
from hyacine.graph.auth import (
    build_credential,
    load_authentication_record,
    save_authentication_record,
)

_state: dict[str, Any] = {"thread": None, "cancel": None}


def start_device_flow(*, emit: Callable[[str, Any], None]) -> dict[str, Any]:
    if _state["thread"] is not None and _state["thread"].is_alive():
        return {"already_running": True}

    s = get_settings()
    cancel = threading.Event()
    _state["cancel"] = cancel

    captured: dict[str, Any] = {}

    def _prompt(verification_uri: str, user_code: str, expires_on: object) -> None:
        captured["user_code"] = user_code
        captured["verification_uri"] = verification_uri
        captured["expires_on"] = str(expires_on)
        emit(
            "graph.device_flow",
            {
                "state": "awaiting_user",
                "user_code": user_code,
                "verification_uri": verification_uri,
            },
        )

    cred = build_credential(
        s.graph_client_id,
        s.graph_tenant_id,
        s.auth_dir,
        disable_automatic_auth=False,
    )
    # Monkey-patch the prompt callback to feed events instead of stdout.
    # DeviceCodeCredential stores the callback as `_prompt_callback`.
    setattr(cred, "_prompt_callback", _prompt)

    def _worker() -> None:
        try:
            record = cred.authenticate(scopes=s.scope_list)
            if cancel.is_set():
                emit("graph.device_flow", {"state": "cancelled"})
                return
            save_authentication_record(record, s.auth_record_path)
            emit("graph.device_flow", {"state": "approved", "username": record.username})
        except Exception as e:  # noqa: BLE001
            emit("graph.device_flow", {"state": "failed", "detail": str(e)})

    t = threading.Thread(target=_worker, name="graph-device-flow", daemon=True)
    _state["thread"] = t
    t.start()
    return {"started": True}


def cancel_device_flow() -> dict[str, Any]:
    c = _state.get("cancel")
    if c is not None:
        c.set()
    return {"ok": True}


def me() -> dict[str, Any]:
    s = get_settings()
    rec = load_authentication_record(s.auth_record_path)
    if rec is None:
        return {"signed_in": False}
    cred = build_credential(s.graph_client_id, s.graph_tenant_id, s.auth_dir, record=rec)
    try:
        token = cred.get_token(*s.scope_list)
        r = httpx.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"authorization": f"Bearer {token.token}"},
            timeout=8.0,
        )
        if r.status_code != 200:
            return {"signed_in": False, "error": f"HTTP {r.status_code}"}
        body = r.json()
        return {
            "signed_in": True,
            "display_name": body.get("displayName", ""),
            "user_principal_name": body.get("userPrincipalName", ""),
            "mail": body.get("mail", ""),
        }
    except Exception as e:  # noqa: BLE001
        return {"signed_in": False, "error": str(e)}
