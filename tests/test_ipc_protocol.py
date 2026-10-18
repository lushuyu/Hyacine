"""Round-trip tests for the JSON-RPC sidecar protocol.

Covers:
  * frame parsing (happy path + garbage)
  * the dispatch loop routes a known method and formats the response
  * params shape validation — object vs array vs anything else
  * handler arity mismatches surface as INVALID_PARAMS instead of crashing

Note on notifications (requests without an ``id``): the JSON-RPC 2.0 spec
requires the server *not* to respond to them, and our ``serve`` loop follows
that rule. The sidecar emits *its own* notifications outbound (progress
events, OAuth polling updates) — those are sent via the ``emit()`` callback
that ``router.build_handlers`` is given, not in response to a request.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from hyacine.ipc import protocol, router
from hyacine.ipc.server import serve


def test_parse_request_ok() -> None:
    msg = protocol.parse_request('{"jsonrpc":"2.0","id":1,"method":"system.ping"}')
    assert msg["method"] == "system.ping"


def test_parse_request_rejects_non_v2() -> None:
    with pytest.raises(protocol.RpcError) as e:
        protocol.parse_request('{"jsonrpc":"1.0","id":1,"method":"x"}')
    assert e.value.code == protocol.INVALID_REQUEST


def test_parse_request_rejects_garbage() -> None:
    with pytest.raises(protocol.RpcError) as e:
        protocol.parse_request("not json")
    assert e.value.code == protocol.PARSE_ERROR


def test_serve_routes_system_ping() -> None:
    stdin = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 42, "method": "system.ping"}) + "\n"
    )
    stdout = io.StringIO()
    stderr = io.StringIO()
    serve(stdin, stdout, stderr)

    lines = [ln for ln in stdout.getvalue().splitlines() if ln.strip()]
    # Last line should be the response to id=42.
    payloads = [json.loads(ln) for ln in lines]
    responses = [p for p in payloads if "id" in p and p["id"] == 42]
    assert responses, f"no response found in {lines}"
    assert responses[0]["result"] == {"pong": True}


def test_serve_unknown_method_returns_error() -> None:
    stdin = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "does.not.exist"}) + "\n"
    )
    stdout = io.StringIO()
    stderr = io.StringIO()
    serve(stdin, stdout, stderr)
    lines = [json.loads(ln) for ln in stdout.getvalue().splitlines() if ln.strip()]
    responses = [p for p in lines if p.get("id") == 1]
    assert responses[0]["error"]["code"] == protocol.METHOD_NOT_FOUND


def test_serve_accepts_positional_params() -> None:
    """`params: []` must reach the handler as *args, not be collapsed to `{}`.

    We send `system.ping` with an empty array — a correctly-implemented
    dispatcher should invoke `ping()` with no kwargs and succeed.
    """
    stdin = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 7, "method": "system.ping", "params": []})
        + "\n"
    )
    stdout = io.StringIO()
    stderr = io.StringIO()
    serve(stdin, stdout, stderr)
    responses = [
        json.loads(ln) for ln in stdout.getvalue().splitlines() if ln.strip()
    ]
    assert any(r.get("id") == 7 and r.get("result") == {"pong": True} for r in responses)


def test_serve_rejects_non_object_non_array_params() -> None:
    stdin = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 9, "method": "system.ping", "params": "no"})
        + "\n"
    )
    stdout = io.StringIO()
    stderr = io.StringIO()
    serve(stdin, stdout, stderr)
    responses = [
        json.loads(ln) for ln in stdout.getvalue().splitlines() if ln.strip()
    ]
    target = next(r for r in responses if r.get("id") == 9)
    assert target["error"]["code"] == protocol.INVALID_PARAMS


def test_serve_translates_handler_typeerror_to_invalid_params() -> None:
    """If a handler gets a kwarg it doesn't accept, the dispatcher should
    report INVALID_PARAMS rather than leaking the raw TypeError."""
    stdin = io.StringIO(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "system.ping",
                "params": {"unexpected": "kwarg"},
            }
        )
        + "\n"
    )
    stdout = io.StringIO()
    stderr = io.StringIO()
    serve(stdin, stdout, stderr)
    responses = [
        json.loads(ln) for ln in stdout.getvalue().splitlines() if ln.strip()
    ]
    target = next(r for r in responses if r.get("id") == 11)
    assert target["error"]["code"] == protocol.INVALID_PARAMS


def test_serve_reports_invalid_config_write_as_invalid_params(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config.yaml"
    monkeypatch.setenv("HYACINE_CONFIG_PATH", str(config))
    stdin = io.StringIO(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 12,
                "method": "config.write",
                "params": {"timezone": "Singapur"},
            }
        )
        + "\n"
    )
    stdout = io.StringIO()
    serve(stdin, stdout, io.StringIO())
    responses = [json.loads(ln) for ln in stdout.getvalue().splitlines() if ln.strip()]
    target = next(r for r in responses if r.get("id") == 12)
    assert target["error"]["code"] == protocol.INVALID_PARAMS
    assert "unknown timezone: 'Singapur'" in target["error"]["message"]
    assert not config.exists()


def test_router_has_no_direct_claude_probe() -> None:
    """The Claude card goes through providers.test. The old direct probe and
    connectivity.probe_all had no callers and sent OAuth tokens in a way the
    API rejects, so they are gone; the probes the desktop uses remain."""
    handlers = router.build_handlers(emit=lambda *_a: None, log=lambda *_a, **_k: None)
    assert "connectivity.probe_all" not in handlers
    assert {"connectivity.probe", "providers.test", "graph.me"} <= handlers.keys()
    assert handlers["connectivity.probe"]("claude")["detail"] == "unknown probe"
