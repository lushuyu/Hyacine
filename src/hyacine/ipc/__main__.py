"""Entry point: `python -m hyacine.ipc`.

Reads newline-delimited JSON-RPC 2.0 requests from stdin, writes responses to
stdout. All structured logging goes to stderr so it doesn't corrupt the RPC
channel.
"""
from __future__ import annotations

import sys

from hyacine.ipc.server import serve


def main() -> int:
    serve(sys.stdin, sys.stdout, sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
