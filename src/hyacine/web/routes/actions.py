"""POST /actions/run — trigger an ad-hoc run.

Tries `systemctl --user start hyacine-run.service` first. Falls back to a
detached `python -m hyacine.pipeline.run` when systemd user isn't available
(e.g. plain WSL shells without `loginctl enable-linger`).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/actions")

# Detect the code directory: the root of the installed/cloned repo.
# __file__ is src/hyacine/web/routes/actions.py → go up 5 levels to repo root.
_CODE_DIR: Path = Path(__file__).resolve().parents[4]


@router.post("/run", response_class=HTMLResponse)
def trigger_run() -> HTMLResponse:
    via = _try_systemctl()
    if via is None:
        via = _spawn_subprocess()
    html = f"<span>Queued ({via})</span>"
    headers = {"HX-Trigger": "runQueued"}
    return HTMLResponse(content=html, headers=headers)


def _try_systemctl() -> str | None:
    """Attempt systemctl --user start. Returns 'systemd' on success, None otherwise."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "start", "hyacine-run.service"],
            check=False,
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            return "systemd"
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _spawn_subprocess() -> str:
    """Detach a background python process and return 'subprocess'."""
    subprocess.Popen(
        [sys.executable, "-m", "hyacine.pipeline.run"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(_CODE_DIR),
    )
    return "subprocess"
