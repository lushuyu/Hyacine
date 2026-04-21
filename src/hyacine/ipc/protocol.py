"""JSON-RPC 2.0 framing helpers.

The sidecar speaks newline-delimited JSON: one request object per stdin line,
one response object per stdout line. Notifications (no `id`) are allowed but
currently unused. Events pushed from server → client (e.g. OAuth polling
updates) are encoded as `{"jsonrpc": "2.0", "method": "event", "params": ...}`
notifications the client can subscribe to.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


@dataclass(frozen=True)
class RpcError(Exception):
    code: int
    message: str
    data: Any = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            out["data"] = self.data
        return out


def ok(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def err(req_id: Any, error: RpcError) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": error.to_dict()}


def event(method: str, params: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "method": method, "params": params}


def parse_request(line: str) -> dict[str, Any]:
    try:
        msg = json.loads(line)
    except json.JSONDecodeError as e:
        raise RpcError(PARSE_ERROR, f"parse error: {e}") from e
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        raise RpcError(INVALID_REQUEST, "not a JSON-RPC 2.0 request")
    if "method" not in msg:
        raise RpcError(INVALID_REQUEST, "missing method")
    return msg
