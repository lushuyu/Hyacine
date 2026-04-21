"""JSON-RPC dispatch loop.

Single-threaded at the request level, but long-running methods (pipeline run,
OAuth polling) push progress events via the injected ``emit`` callable so the
Rust parent can forward them to the webview. Those emits can and do run on
background threads (see ``graph_h.start_device_flow``), so every stdout
write is guarded by a ``threading.Lock`` to keep newline-delimited framing
intact under concurrent producers.
"""
from __future__ import annotations

import inspect
import json
import threading
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
    # `write_lock` fences every stdout.write + flush so background-thread emits
    # can't interleave with a response the dispatch loop is mid-way through
    # writing. Stderr only has a single writer (this module) so it doesn't
    # need one.
    write_lock = threading.Lock()

    def _write_frame(frame: dict[str, Any]) -> None:
        line = json.dumps(frame) + "\n"
        with write_lock:
            stdout.write(line)
            stdout.flush()

    def emit(method: str, params: Any) -> None:
        _write_frame(event(method, params))

    def log(level: str, msg: str, **extra: Any) -> None:
        # Stderr has a single producer (this loop), so no lock needed.
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
            if not isinstance(params, (dict, list)):
                raise RpcError(
                    INVALID_PARAMS,
                    f"params must be object or array, got {type(params).__name__}",
                )

            # Validate arity up-front with inspect.signature().bind() so a
            # signature mismatch surfaces as INVALID_PARAMS while TypeErrors
            # raised *inside* the handler fall through to INTERNAL_ERROR and
            # don't get mis-reported as a caller bug.
            try:
                sig = inspect.signature(handler)
                if isinstance(params, dict):
                    sig.bind(**params)
                else:
                    sig.bind(*params)
            except TypeError as bind_err:
                raise RpcError(INVALID_PARAMS, str(bind_err)) from bind_err

            if isinstance(params, dict):
                result = handler(**params)
            else:
                result = handler(*params)

            if req_id is not None:
                _write_frame(ok(req_id, result))
        except RpcError as e:
            log("error", "rpc-error", code=e.code, message=e.message)
            if req_id is not None:
                _write_frame(err(req_id, e))
        except Exception as e:  # noqa: BLE001
            log("error", "unhandled", trace=traceback.format_exc())
            if req_id is not None:
                _write_frame(err(req_id, RpcError(INTERNAL_ERROR, str(e))))
