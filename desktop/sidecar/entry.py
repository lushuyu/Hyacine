"""PyInstaller entry point for the bundled ``hyacine-ipc`` sidecar.

Thin wrapper: imports the real ``main`` from :mod:`hyacine.ipc.__main__`
and invokes it. Keeping this a separate file (rather than pointing
PyInstaller at the module directly) gives us a stable location for the
pre-``main`` environment tweaks a frozen binary needs.

Data root: in a one-file build ``hyacine/config.py`` lives under the
PyInstaller extraction dir, so its ``Path(__file__).parents[2]`` fallback
is the OS temp dir, and config.yaml, the watermark DB and the Graph auth
record would land there (wiped on reboot, shared between users on Linux).
The Tauri parent passes ``HYACINE_REPO_ROOT``; when the binary runs without
it, pin the same per-user directory before ``hyacine`` is imported, since
config.py fixes its ``.env`` path at import time.

Stdio encoding is handled in ``hyacine-ipc.spec`` (``X utf8``): a frozen
interpreter ignores ``PYTHONUTF8`` / ``PYTHONIOENCODING``.
"""
from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

# Must match "identifier" in desktop/src-tauri/tauri.conf.json: the Rust side
# uses Tauri's app_local_data_dir(), which is <local data dir>/<identifier>.
APP_IDENTIFIER = "com.hyacine.desktop"


def default_data_root(
    platform: str = sys.platform,
    environ: Mapping[str, str] = os.environ,
    home: Path | None = None,
) -> Path:
    """Per-user data dir, same as Tauri's ``app_local_data_dir()``."""
    home = home if home is not None else Path.home()
    if platform == "win32":
        base = Path(environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    elif platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        xdg = environ.get("XDG_DATA_HOME", "")
        # The XDG spec says to ignore a relative value.
        base = Path(xdg) if os.path.isabs(xdg) else home / ".local" / "share"
    return base / APP_IDENTIFIER


def pin_data_root() -> None:
    """Point ``HYACINE_REPO_ROOT`` at the per-user dir in a frozen build."""
    if not getattr(sys, "frozen", False):
        return
    if os.environ.get("HYACINE_REPO_ROOT", "").strip():
        return
    root = default_data_root()
    root.mkdir(parents=True, exist_ok=True)
    os.environ["HYACINE_REPO_ROOT"] = str(root)


def run() -> int:
    pin_data_root()
    # Imported here, after the env is set: hyacine.config reads
    # HYACINE_REPO_ROOT at import time.
    from hyacine.ipc.__main__ import main

    return main()


if __name__ == "__main__":
    sys.exit(run())
