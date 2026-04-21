"""JSON-RPC dispatch loop.

Single-threaded, one request at a time. Long-running methods (pipeline run,
OAuth polling) push progress events via the injected ``emit`` callable so the
Rust parent can forward them to the webview.
"""
from __future__ import annotations

import json
import traceback
from collections.abc import Callable
from typing import IO, Any

from hyacine.ipc import router
from hyacine.ipc.protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    RpcError,
    err,
    event,
    ok,
    parse_request,
)


def serve(stdin: IO[str], stdout: IO[str], stderr: IO[str]) -> None:
    def emit(method: str, params: Any) -> None:
        stdout.write(json.dumps(event(method, params)) + "\n")
        stdout.flush()

    def log(level: str, msg: str, **extra: Any) -> None:
        stderr.write(json.dumps({"level": level, "msg": msg, **extra}) + "\n")
        stderr.flush()

    handlers = router.build_handlers(emit=emit, log=log)
    log("info", "sidecar-ready", methods=sorted(handlers.keys()))

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        req_id: Any = None
        try:
            msg = parse_request(line)
            req_id = msg.get("id")
            method = msg["method"]
            params = msg.get("params", {})

            handler: Callable[..., Any] | None = handlers.get(method)
            if handler is None:
                raise RpcError(METHOD_NOT_FOUND, f"method not found: {method}")

            # JSON-RPC 2.0 allows params to be absent, an object, or an array.
            # Anything else is a protocol error — and note that we specifically
            # DON'T collapse `[]` to `{}`; an empty positional list is a valid
            # call that just happens to pass no args.
            if isinstance(params, dict):
                result = handler(**params)
            elif isinstance(params, list):
                result = handler(*params)
            else:
                raise RpcError(
                    INVALID_PARAMS,
                    f"params must be object or array, got {type(params).__name__}",
                )

            if req_id is not None:
                stdout.write(json.dumps(ok(req_id, result)) + "\n")
                stdout.flush()
        except RpcError as e:
            log("error", "rpc-error", code=e.code, message=e.message)
            if req_id is not None:
                stdout.write(json.dumps(err(req_id, e)) + "\n")
                stdout.flush()
        except TypeError as e:
            # Handler arity / keyword mismatches surface here — report as
            # INVALID_PARAMS so callers can distinguish from an internal bug.
            log("error", "invalid-params", trace=traceback.format_exc())
            if req_id is not None:
                stdout.write(
                    json.dumps(err(req_id, RpcError(INVALID_PARAMS, str(e)))) + "\n"
                )
                stdout.flush()
        except Exception as e:  # noqa: BLE001
            log("error", "unhandled", trace=traceback.format_exc())
            if req_id is not None:
                stdout.write(
                    json.dumps(err(req_id, RpcError(INTERNAL_ERROR, str(e)))) + "\n"
                )
                stdout.flush()
