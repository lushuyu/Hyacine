"""Connectivity probes — DNS/TCP, Claude API, Microsoft Graph, SendMail.

Every probe returns ``{kind, status: ok|fail|skipped, latency_ms, detail}``.
Events ``connectivity.progress`` are emitted as each probe transitions so the
UI can animate running → ok/fail.

The Claude probe authenticates with whatever the user stored — Anthropic API
key (``x-api-key`` header) *or* Claude Code OAuth token (``Authorization:
Bearer``). The wizard's keychain slug is fixed (``claude``) but callers pass
the actual value in, so we accept both shapes here.
"""
from __future__ import annotations

import socket
import time
from collections.abc import Callable
from typing import Any

import httpx

from hyacine.config import get_settings, load_yaml_config
from hyacine.ipc.handlers.graph_h import _get_access_token

_HOSTS = ("api.anthropic.com", "graph.microsoft.com")


def _now_ms() -> int:
    return int(time.monotonic() * 1000)


def _dns_tcp(host: str, port: int = 443, timeout: float = 4.0) -> tuple[bool, str]:
    """Resolve *host* (A and AAAA) and attempt a TCP connect.

    Prefer :func:`socket.getaddrinfo` so an IPv6-only network — or a host
    that only publishes AAAA records — still resolves cleanly.
    ``create_connection`` walks the address list, so a single successful
    connect short-circuits; we surface the address we actually reached in
    the detail string so the UI can show whether it was IPv4 or IPv6.
    """
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError as e:
        return False, f"DNS: {e}"
    if not infos:
        return False, "DNS: no addresses"
    last_err: str | None = None
    for family, socktype, proto, _canon, sockaddr in infos:
        try:
            with socket.socket(family, socktype, proto) as sock:
                sock.settimeout(timeout)
                sock.connect(sockaddr)
                ip = sockaddr[0]
                return True, f"{host} → {ip}:{port}"
        except OSError as e:
            last_err = str(e)
            continue
    return False, f"TCP: {last_err or 'unreachable'}"


def _default_claude_model() -> str:
    """Use the model configured by the user, not a hard-coded guess."""
    try:
        cfg = load_yaml_config(get_settings().config_path)
        return cfg.llm_model or "sonnet"
    except Exception:  # noqa: BLE001
        return "sonnet"


def probe_dns(**_: Any) -> dict[str, Any]:
    start = _now_ms()
    details: list[str] = []
    all_ok = True
    for h in _HOSTS:
        ok, d = _dns_tcp(h)
        details.append(d)
        all_ok = all_ok and ok
    return {
        "kind": "dns",
        "status": "ok" if all_ok else "fail",
        "latency_ms": _now_ms() - start,
        "detail": "; ".join(details),
    }


def probe_claude(api_key: str = "", model: str = "", **_: Any) -> dict[str, Any]:
    """Reachability probe for the Anthropic API.

    Anthropic issues two token shapes under the ``sk-ant-`` prefix:

      * ``sk-ant-api*`` — Console API key → ``x-api-key`` header
      * ``sk-ant-oat*`` — Claude Code OAuth token → ``Authorization: Bearer``

    Anything else (bare bearer, JWT, etc.) goes through ``Authorization:
    Bearer``. Sending an OAuth token in ``x-api-key`` produces a 401 with
    ``{"message": "invalid x-api-key"}`` which is what motivated this split.
    """
    if not api_key:
        return {"kind": "claude", "status": "skipped", "latency_ms": 0, "detail": "no api key"}
    model = model or _default_claude_model()
    start = _now_ms()

    headers = {"anthropic-version": "2023-06-01", "content-type": "application/json"}
    if api_key.startswith("sk-ant-api"):
        headers["x-api-key"] = api_key
    else:
        headers["authorization"] = f"Bearer {api_key}"

    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json={
                "model": model,
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "ping"}],
            },
            timeout=10.0,
        )
        latency = _now_ms() - start
        if r.status_code == 200:
            return {
                "kind": "claude",
                "status": "ok",
                "latency_ms": latency,
                "detail": f"HTTP 200, model={model}",
            }
        return {
            "kind": "claude",
            "status": "fail",
            "latency_ms": latency,
            "detail": f"HTTP {r.status_code}: {r.text[:200]}",
        }
    except httpx.HTTPError as e:
        return {
            "kind": "claude",
            "status": "fail",
            "latency_ms": _now_ms() - start,
            "detail": str(e),
        }


def probe_graph(access_token: str = "", **_: Any) -> dict[str, Any]:
    """Hit ``/me`` using either a supplied token or the cached MSAL record."""
    token = access_token or _get_access_token() or ""
    if not token:
        return {"kind": "graph", "status": "skipped", "latency_ms": 0, "detail": "not signed in"}
    start = _now_ms()
    try:
        r = httpx.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        latency = _now_ms() - start
        if r.status_code == 200:
            body = r.json()
            return {
                "kind": "graph",
                "status": "ok",
                "latency_ms": latency,
                "detail": f"{body.get('displayName', '')} <{body.get('userPrincipalName', '')}>",
            }
        return {
            "kind": "graph",
            "status": "fail",
            "latency_ms": latency,
            "detail": f"HTTP {r.status_code}",
        }
    except httpx.HTTPError as e:
        return {
            "kind": "graph",
            "status": "fail",
            "latency_ms": _now_ms() - start,
            "detail": str(e),
        }


def probe_sendmail(to: str = "", access_token: str = "", **_: Any) -> dict[str, Any]:
    """Send a one-shot test email to the user. Token defaults to the cached
    MSAL record, so the Rust parent doesn't have to forward it."""
    if not to:
        return {
            "kind": "sendmail",
            "status": "skipped",
            "latency_ms": 0,
            "detail": "missing recipient",
        }
    token = access_token or _get_access_token() or ""
    if not token:
        return {
            "kind": "sendmail",
            "status": "skipped",
            "latency_ms": 0,
            "detail": "not signed in",
        }
    start = _now_ms()
    body = {
        "message": {
            "subject": "Hyacine setup test",
            "body": {
                "contentType": "Text",
                "content": "This is a one-time connectivity test from Hyacine setup.",
            },
            "toRecipients": [{"emailAddress": {"address": to}}],
        },
        "saveToSentItems": False,
    }
    try:
        r = httpx.post(
            "https://graph.microsoft.com/v1.0/me/sendMail",
            headers={
                "authorization": f"Bearer {token}",
                "content-type": "application/json",
            },
            json=body,
            timeout=15.0,
        )
        latency = _now_ms() - start
        if r.status_code in (200, 202):
            return {
                "kind": "sendmail",
                "status": "ok",
                "latency_ms": latency,
                "detail": f"queued to {to}",
            }
        return {
            "kind": "sendmail",
            "status": "fail",
            "latency_ms": latency,
            "detail": f"HTTP {r.status_code}: {r.text[:200]}",
        }
    except httpx.HTTPError as e:
        return {
            "kind": "sendmail",
            "status": "fail",
            "latency_ms": _now_ms() - start,
            "detail": str(e),
        }


# Each entry is a callable that accepts **kwargs so the dispatcher can forward
# RPC params without knowing the probe's exact signature.
_DISPATCH: dict[str, Callable[..., dict[str, Any]]] = {
    "dns": probe_dns,
    "claude": probe_claude,
    "graph": probe_graph,
    "sendmail": probe_sendmail,
}


def probe(
    kind: str,
    *,
    emit: Callable[[str, Any], None],
    **kwargs: Any,
) -> dict[str, Any]:
    fn = _DISPATCH.get(kind)
    if fn is None:
        return {"kind": kind, "status": "fail", "latency_ms": 0, "detail": "unknown probe"}
    emit("connectivity.progress", {"kind": kind, "status": "running"})
    result = fn(**kwargs)
    emit("connectivity.progress", result)
    return result


def probe_all(
    *,
    emit: Callable[[str, Any], None],
    claude_api_key: str = "",
    graph_token: str = "",
    recipient: str = "",
    send_test_email: bool = False,
) -> dict[str, Any]:
    results = [
        probe("dns", emit=emit),
        probe("claude", emit=emit, api_key=claude_api_key),
        probe("graph", emit=emit, access_token=graph_token),
    ]
    if send_test_email:
        results.append(probe("sendmail", emit=emit, access_token=graph_token, to=recipient))
    return {"results": results, "ok": all(r["status"] != "fail" for r in results)}
