"""Connectivity probes — DNS/TCP, Claude API, Microsoft Graph, SendMail.

Every probe returns `{kind, status: ok|fail|skipped, latency_ms, detail}`.
Events `connectivity.progress` are emitted as each probe transitions.
"""
from __future__ import annotations

import socket
import time
from collections.abc import Callable
from typing import Any

import httpx

ProbeKind = str
_HOSTS = ["api.anthropic.com", "graph.microsoft.com"]


def _now_ms() -> int:
    return int(time.monotonic() * 1000)


def _dns_tcp(host: str, port: int = 443, timeout: float = 4.0) -> tuple[bool, str]:
    try:
        ip = socket.gethostbyname(host)
    except OSError as e:
        return False, f"DNS: {e}"
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True, f"{host} → {ip}:{port}"
    except OSError as e:
        return False, f"TCP: {e}"


def probe_dns() -> dict[str, Any]:
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


def probe_claude(api_key: str, model: str = "claude-haiku-4-5") -> dict[str, Any]:
    if not api_key:
        return {"kind": "claude", "status": "skipped", "latency_ms": 0, "detail": "no api key"}
    start = _now_ms()
    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
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


def probe_graph(access_token: str = "") -> dict[str, Any]:
    if not access_token:
        return {"kind": "graph", "status": "skipped", "latency_ms": 0, "detail": "no token"}
    start = _now_ms()
    try:
        r = httpx.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"authorization": f"Bearer {access_token}"},
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


def probe_sendmail(access_token: str, to: str) -> dict[str, Any]:
    if not access_token or not to:
        return {
            "kind": "sendmail",
            "status": "skipped",
            "latency_ms": 0,
            "detail": "missing token or recipient",
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
                "authorization": f"Bearer {access_token}",
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


_DISPATCH = {
    "dns": lambda **_: probe_dns(),
    "claude": probe_claude,
    "graph": probe_graph,
    "sendmail": probe_sendmail,
}


def probe(
    kind: ProbeKind,
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
