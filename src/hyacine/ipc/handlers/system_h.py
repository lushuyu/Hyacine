"""System-level RPC handlers — ping, version, resolved paths."""
from __future__ import annotations

import platform
from typing import Any

from hyacine import __version__
from hyacine.config import get_settings


def ping() -> dict[str, Any]:
    return {"pong": True}


def version() -> dict[str, Any]:
    return {
        "hyacine": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def paths() -> dict[str, str]:
    s = get_settings()
    return {
        "config": str(s.config_path),
        "rules": str(s.rules_path),
        "prompt": str(s.prompt_path),
        "db": str(s.db_path),
        "auth_dir": str(s.auth_dir),
        "log_dir": str(s.log_dir),
    }
