"""POST /actions/run — trigger an ad-hoc run.

Tries `systemctl --user start --no-block hyacine-run.service` first. The unit
is Type=oneshot, so a blocking start would wait out the whole 30-90 s run;
--no-block only enqueues the job. Falls back to a detached
`python -m hyacine.pipeline.run` when systemd user isn't available (e.g. plain
WSL shells without `loginctl enable-linger`) or the unit isn't installed.
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

_SYSTEMCTL_TIMEOUT_HTML = (
    "<span>systemctl did not answer in time; the run may already be queued. "
    "Check the dashboard or <code>systemctl --user status hyacine-run.service</code> "
    "before retrying.</span>"
)


@router.post("/run", response_class=HTMLResponse)
def trigger_run() -> HTMLResponse:
    try:
        via = _try_systemctl()
    except subprocess.TimeoutExpired:
        # The start job may already be enqueued; spawning the fallback here
        # would race it with a second concurrent pipeline.
        return HTMLResponse(content=_SYSTEMCTL_TIMEOUT_HTML)
    if via is None:
        via = _spawn_subprocess()
    html = f"<span>Queued ({via})</span>"
    headers = {"HX-Trigger": "runQueued"}
    return HTMLResponse(content=html, headers=headers)


def _try_systemctl() -> str | None:
    """Enqueue hyacine-run.service via systemctl --user.

    Returns 'systemd' on success, None when systemd user isn't usable (binary
    missing, no user bus, unit not installed). TimeoutExpired propagates: the
    job may already be queued, so the caller must not fall back.
    """
    try:
        result = subprocess.run(
            ["systemctl", "--user", "start", "--no-block", "hyacine-run.service"],
            check=False,
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            return "systemd"
        return None
    except FileNotFoundError:
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
