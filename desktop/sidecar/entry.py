"""PyInstaller entry point for the bundled ``hyacine-ipc`` sidecar.

Thin wrapper: imports the real ``main`` from :mod:`hyacine.ipc.__main__`
and invokes it. Keeping this a separate file (rather than pointing
PyInstaller at the module directly) gives us a stable location for any
pre-``main`` environment tweaks a frozen binary might need later (e.g.
setting ``PYTHONUTF8=1`` on Windows before stdio is opened).
"""
from __future__ import annotations

import sys

from hyacine.ipc.__main__ import main


if __name__ == "__main__":
    sys.exit(main())
