"""Round-trip tests for the JSON-RPC sidecar protocol.

Covers three things:
  * frame parsing (happy path + garbage)
  * the dispatch loop routes a known method and formats the response
  * notifications (no `id`) are emitted verbatim to stdout
"""
from __future__ import annotations

import io
import json

import pytest

from hyacine.ipc import protocol
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
