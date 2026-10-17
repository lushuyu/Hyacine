"""Entry point: `python -m hyacine.ipc`.

Reads newline-delimited JSON-RPC 2.0 requests from stdin, writes responses to
stdout. All structured logging goes to stderr so it doesn't corrupt the RPC
channel.
"""
from __future__ import annotations

import sys

from hyacine.ipc.server import serve


def _use_utf8_stdio() -> None:
    """Pin the RPC channel to UTF-8, whatever the OS locale says.

    The Rust parent writes raw UTF-8 JSON (serde_json does not escape
    non-ASCII) and decodes our stdout/stderr as UTF-8. On Windows, Python
    before 3.15 decodes piped stdio with the ANSI code page (cp1252, cp936,
    ...) unless UTF-8 mode is on, so a zh-CN prompt either kills the read
    loop with UnicodeDecodeError or is saved as mojibake. This changes
    nothing where the locale is already UTF-8 (Linux, macOS). It has to run
    before anything reads stdin, as the encoding can't change after a read.
    """
    for stream, errors in (
        (sys.stdin, "strict"),
        (sys.stdout, "strict"),
        # stderr keeps its usual handler so a stray log line can't crash us.
        (sys.stderr, "backslashreplace"),
    ):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors=errors)


def main() -> int:
    _use_utf8_stdio()
    serve(sys.stdin, sys.stdout, sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
