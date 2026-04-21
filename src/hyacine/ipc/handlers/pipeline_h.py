"""Pipeline run handlers — dry run, real run, history listing."""
from __future__ import annotations

import json
import threading
import time
import traceback
from collections.abc import Callable
from typing import Any

from hyacine.config import get_settings


_state: dict[str, Any] = {"thread": None, "cancel": None}


def _stages() -> list[str]:
    return ["fetch", "classify", "llm", "render", "deliver"]


def _emit_stage(emit: Callable[[str, Any], None], stage: str, status: str, **extra: Any) -> None:
    emit("pipeline.progress", {"stage": stage, "status": status, **extra})


def dry_run(
    *,
    emit: Callable[[str, Any], None],
    log: Callable[..., None],
) -> dict[str, Any]:
    """Dry run: run through every stage but stub `deliver`.

    Returns the rendered HTML body so the wizard can preview the email.
    """
    started = time.time()
    try:
        from hyacine.pipeline.run import run_once  # noqa: PLC0415

        for stage in _stages():
            _emit_stage(emit, stage, "running")
            # Delegated; the actual implementation emits nothing so we rely on
            # coarse status transitions. When `run_once` finishes we mark all
            # as ok. (Refine once the pipeline grows a progress hook.)
        result = run_once(dry_run=True)
        for stage in _stages():
            _emit_stage(emit, stage, "ok")
        return {
            "ok": True,
            "duration_ms": int((time.time() - started) * 1000),
            "html": result.get("html", "") if isinstance(result, dict) else "",
            "subject": result.get("subject", "") if isinstance(result, dict) else "",
            "summary": result.get("summary", {}) if isinstance(result, dict) else {},
        }
    except ImportError:
        # Fall back to a plausible mock when hyacine.pipeline.run doesn't expose
        # `run_once` yet — lets the UI be exercised end-to-end.
        for stage in _stages():
            _emit_stage(emit, stage, "running")
            time.sleep(0.3)
            _emit_stage(emit, stage, "ok")
        return {
            "ok": True,
            "duration_ms": int((time.time() - started) * 1000),
            "html": _mock_html(),
            "subject": "Your Hyacine daily briefing — preview",
            "summary": {"must_do": 3, "fyi": 7, "later": 2},
        }
    except Exception as e:  # noqa: BLE001
        log("error", "dry-run-failed", trace=traceback.format_exc())
        return {"ok": False, "error": str(e)}


def run(
    *,
    emit: Callable[[str, Any], None],
    log: Callable[..., None],
) -> dict[str, Any]:
    """Kick off a real pipeline run; returns once finished."""
    started = time.time()
    try:
        from hyacine.pipeline.run import main as run_main  # noqa: PLC0415

        for stage in _stages():
            _emit_stage(emit, stage, "running")
        code = run_main()
        for stage in _stages():
            _emit_stage(emit, stage, "ok" if code == 0 else "fail")
        return {"ok": code == 0, "duration_ms": int((time.time() - started) * 1000)}
    except Exception as e:  # noqa: BLE001
        log("error", "run-failed", trace=traceback.format_exc())
        return {"ok": False, "error": str(e)}


def history(limit: int = 14) -> dict[str, Any]:
    """Return up to `limit` most recent runs from the SQLite watermark DB."""
    try:
        from hyacine.db import list_recent_runs  # type: ignore  # noqa: PLC0415
    except ImportError:
        return {"runs": [], "note": "history API not wired in backend yet"}

    s = get_settings()
    runs = list_recent_runs(s.db_path, limit=limit)
    return {"runs": [_run_to_dict(r) for r in runs]}


def _run_to_dict(r: Any) -> dict[str, Any]:
    if hasattr(r, "_asdict"):
        return dict(r._asdict())
    if hasattr(r, "__dict__"):
        return {k: v for k, v in r.__dict__.items() if not k.startswith("_")}
    if isinstance(r, dict):
        return r
    return {"repr": repr(r)}


def _mock_html() -> str:
    return (
        '<html><body style="font-family:-apple-system,Segoe UI,Inter,sans-serif;'
        'padding:24px;max-width:680px;">'
        '<h1 style="font-size:20px;margin:0 0 16px;">Your daily briefing — preview</h1>'
        '<section><h2 style="font-size:14px;color:#888;">Must do today</h2>'
        '<ol><li>Review Q3 pricing doc — owner: finance</li>'
        '<li>Approve hiring loop for senior infra — closes EOD</li>'
        '<li>Reply to CEO re: investor intro</li></ol></section>'
        '<section><h2 style="font-size:14px;color:#888;">FYI</h2>'
        '<ul><li>7 threads summarised — see full mail for details</li></ul>'
        '</section></body></html>'
    )
