"""Microsoft Graph device-code OAuth handlers.

The flow is split across three calls so the webview can animate polling:

  1. ``graph.start_device_flow``  → returns user_code + verification_uri;
                                    spawns a background poll that emits
                                    ``graph.device_flow`` events until
                                    approval, expiry, or cancellation.
  2. ``graph.cancel_device_flow`` → client aborts before approval.
  3. ``graph.me``                 → once a record exists, fetch profile for
                                    the "signed in as" badge.

Cancellation caveat: ``DeviceCodeCredential.authenticate`` blocks in a
background thread and has no interrupt hook (a ``timeout`` passed to it is
ignored; one passed to the constructor ends the whole flow with an error).
A cancelled worker is therefore abandoned: it keeps polling until its code
expires (about 15 minutes) or the user approves/denies, then exits without
saving the record, and stays silent if a newer flow has started meanwhile.
A new ``graph.start_device_flow`` doesn't wait for it; it starts a fresh
flow with a new code straight away.
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

# The current flow: its worker thread, its cancel event (which doubles as the
# flow's identity) and its last "awaiting_user" payload, kept so a page that
# remounts mid-flow is shown the code again. A superseded worker sees that
# ``_state["cancel"]`` is no longer its own event and stays silent. ``_lock``
# makes that check plus the emit atomic with respect to a new start.
_state: dict[str, Any] = {"thread": None, "cancel": None, "prompt": None}
_lock = threading.Lock()


def start_device_flow(*, emit: Callable[[str, Any], None]) -> dict[str, Any]:
    with _lock:
        thread, live_cancel = _state["thread"], _state["cancel"]
        if (
            thread is not None
            and thread.is_alive()
            and live_cancel is not None
            and not live_cancel.is_set()
        ):
            if _state["prompt"] is not None:
                emit("graph.device_flow", _state["prompt"])
            return {"already_running": True}
        # No flow, or only a cancelled one still polling: abandon it.
        cancel = threading.Event()
        _state.update(thread=None, cancel=cancel, prompt=None)

    s = get_settings()

    def _current() -> bool:
        return _state["cancel"] is cancel

    def _prompt(verification_uri: str, user_code: str, expires_on: object) -> None:
        payload = {
            "state": "awaiting_user",
            "user_code": user_code,
            "verification_uri": verification_uri,
            "expires_on": str(expires_on),
        }
        with _lock:
            if _current() and not cancel.is_set():
                _state["prompt"] = payload
                emit("graph.device_flow", payload)

    def _finish(payload: dict[str, Any]) -> None:
        with _lock:
            if _current():
                _state["prompt"] = None
                emit("graph.device_flow", payload)

    cred = build_credential(
        s.graph_client_id,
        s.graph_tenant_id,
        s.auth_dir,
        disable_automatic_auth=False,
        prompt_callback=_prompt,
    )

    def _worker() -> None:
        try:
            record = cred.authenticate(scopes=s.scope_list)
            if cancel.is_set():
                _finish({"state": "cancelled"})
                return
            save_authentication_record(record, s.auth_record_path)
            _finish({"state": "approved", "username": record.username})
        except Exception as e:  # noqa: BLE001
            if cancel.is_set():
                _finish({"state": "cancelled"})
            else:
                _finish({"state": "failed", "detail": str(e)})

    t = threading.Thread(target=_worker, name="graph-device-flow", daemon=True)
    with _lock:
        _state["thread"] = t
    t.start()
    return {"started": True}


def cancel_device_flow() -> dict[str, Any]:
    """Signal the worker to abandon the flow.

    ``azure-identity``'s device-code implementation does not expose a
    cancellation primitive, so we set a flag and let the worker swallow the
    eventual expiry (or the user-approved record) without persisting it.
    The next ``start_device_flow`` replaces the flow instead of waiting.
    """
    with _lock:
        c = _state.get("cancel")
        if c is not None:
            c.set()
        _state["prompt"] = None
    return {"ok": True}


def me() -> dict[str, Any]:
    s = get_settings()
    rec = load_authentication_record(s.auth_record_path)
    if rec is None:
        return {"signed_in": False}
    # disable_automatic_auth=True → silent-refresh only; a cache miss raises
    # AuthenticationRequiredError instead of triggering a fresh device-code
    # flow. Without this, an expired record would drag the main dispatch
    # thread into an 8s MSAL flow and print the verification prompt to
    # stdout, corrupting the JSON-RPC channel.
    cred = build_credential(
        s.graph_client_id,
        s.graph_tenant_id,
        s.auth_dir,
        record=rec,
        disable_automatic_auth=True,
    )
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


def _get_access_token() -> str | None:
    """Fetch a bearer token using the cached MSAL record.

    Returned ``None`` if the record doesn't exist (user hasn't completed
    device-code yet) so connectivity probes can report "skipped" cleanly.
    """
    s = get_settings()
    rec = load_authentication_record(s.auth_record_path)
    if rec is None:
        return None
    # See `me()` for the reasoning behind disable_automatic_auth=True.
    cred = build_credential(
        s.graph_client_id,
        s.graph_tenant_id,
        s.auth_dir,
        record=rec,
        disable_automatic_auth=True,
    )
    try:
        return cred.get_token(*s.scope_list).token
    except Exception:  # noqa: BLE001
        return None
