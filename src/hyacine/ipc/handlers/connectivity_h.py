"""Connectivity probes — DNS/TCP, Microsoft Graph, SendMail.

Every probe returns ``{kind, status: ok|fail|skipped, latency_ms, detail}``.
Events ``connectivity.progress`` are emitted as each probe transitions so the
UI can animate running → ok/fail.

The LLM check is not here: the wizard's Claude card goes through
``providers.test`` (see :mod:`hyacine.ipc.handlers.providers_h`), which
probes whichever provider is configured, with the same code paths the
daily run uses.
"""
from __future__ import annotations

import socket
import time
from collections.abc import Callable
from typing import Any

import httpx

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

