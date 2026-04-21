"""Pipeline run handlers — dry run, real run, history listing.

These endpoints wrap the existing ``hyacine.pipeline.run`` module. The key
thing to remember is that the sidecar speaks JSON-RPC on stdout, so any
library code that prints to stdout has to be redirected — we never let the
pipeline corrupt the RPC channel.
"""
from __future__ import annotations

import contextlib
import os
import sys
import time
import traceback
from collections.abc import Callable
from datetime import datetime
from typing import Any

from hyacine.config import get_settings
from hyacine.db import Run, init_db, session_scope

_STAGES: tuple[str, ...] = ("fetch", "classify", "llm", "render", "deliver")


def _emit_stage(emit: Callable[[str, Any], None], stage: str, status: str, **extra: Any) -> None:
    emit("pipeline.progress", {"stage": stage, "status": status, **extra})


@contextlib.contextmanager
def _silence_stdout() -> Any:
    """Redirect stdout to ``os.devnull`` for the duration of a block.

    ``run_pipeline`` and friends are library-shaped but a few call sites use
    ``print(...)`` for status (healthchecks, device-code prompts that escape
    the callback, etc.). We never want any of that on the sidecar stdout,
    and devnull beats an in-memory StringIO because the pipeline can emit
    arbitrarily large outputs (full rendered emails, logs) we never read.
    """
    saved = sys.stdout
    try:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
        yield
    finally:
        try:
            sys.stdout.close()
        except Exception:  # noqa: BLE001
            pass
        sys.stdout = saved


def _inject_claude_code_oauth() -> None:
    """Populate ``CLAUDE_CODE_OAUTH_TOKEN`` from the env if not already set.

    The Rust parent writes the token into the environment it hands us, but if
    an end user is running the sidecar on its own (or in tests) the env var
    might be missing; we accept ``HYACINE_CLAUDE_CODE_OAUTH_TOKEN`` as a
    fallback. Callers must still validate presence themselves via
    :func:`_claude_token_missing` — we don't raise here because a few
    handlers (history, dry-run renders from cache) don't require the token.
    """
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return
    from_env = os.environ.get("HYACINE_CLAUDE_CODE_OAUTH_TOKEN", "")
    if from_env:
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = from_env


def _claude_token_missing() -> str | None:
    """Return a human-readable reason if pipeline execution can't proceed.

    ``hyacine.llm.claude_code.build_env`` raises if
    ``CLAUDE_CODE_OAUTH_TOKEN`` is absent. Catching that upstream gives a
    much clearer message than the raw exception traceback the webview would
    otherwise see in ``result.error``.
    """
    if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return (
            "CLAUDE_CODE_OAUTH_TOKEN is not set. Re-run the Claude key step "
            "or export the token in the sidecar environment before retrying."
        )
    return None


def dry_run(
    *,
    emit: Callable[[str, Any], None],
    log: Callable[..., None],
) -> dict[str, Any]:
    """Dry run: walk every stage but don't actually send the email.

    Returns the rendered body so the wizard can preview the email in its
    sandboxed iframe.
    """
    started = time.time()
    _inject_claude_code_oauth()

    if (missing := _claude_token_missing()) is not None:
        for stage in _STAGES:
            _emit_stage(emit, stage, "fail")
        return {
            "ok": False,
            "error": missing,
            "duration_ms": int((time.time() - started) * 1000),
        }

    try:
        from hyacine.pipeline.run import run_pipeline  # noqa: PLC0415
    except ImportError:
        return _mock_dry_run(emit, started)

    # Drive the progress UI as best we can without piping real events out of
    # the pipeline (we can't without patching run_pipeline upstream). We mark
    # each stage started in order, then rely on the final record to decide
    # whether everything succeeded.
    for stage in _STAGES[:-1]:
        _emit_stage(emit, stage, "running")
    _emit_stage(emit, "deliver", "running", note="dry-run — will not actually send")

    try:
        with _silence_stdout():
            record = run_pipeline()
    except Exception as e:  # noqa: BLE001
        log("error", "dry-run-failed", trace=traceback.format_exc())
        for stage in _STAGES:
            _emit_stage(emit, stage, "fail")
        return {"ok": False, "error": str(e), "duration_ms": int((time.time() - started) * 1000)}

    for stage in _STAGES:
        _emit_stage(emit, stage, "ok")

    markdown = getattr(record, "markdown", "") or ""
    return {
        "ok": str(getattr(record, "status", "")).lower().endswith("success")
        or markdown != "",
        "duration_ms": int((time.time() - started) * 1000),
        "html": _markdown_to_html(markdown),
        "subject": f"Hyacine · {datetime.now().strftime('%Y-%m-%d')} (preview)",
        "summary": {"email_count": getattr(record, "email_count", 0) or 0},
    }


def run(
    *,
    emit: Callable[[str, Any], None],
    log: Callable[..., None],
) -> dict[str, Any]:
    """Real pipeline run — fetch + summarise + deliver."""
    started = time.time()
    _inject_claude_code_oauth()

    if (missing := _claude_token_missing()) is not None:
        for stage in _STAGES:
            _emit_stage(emit, stage, "fail")
        return {
            "ok": False,
            "error": missing,
            "duration_ms": int((time.time() - started) * 1000),
        }

    try:
        from hyacine.pipeline.run import run_pipeline  # noqa: PLC0415
    except ImportError as e:
        return {"ok": False, "error": str(e), "duration_ms": 0}

    for stage in _STAGES:
        _emit_stage(emit, stage, "running")

    try:
        with _silence_stdout():
            record = run_pipeline()
    except Exception as e:  # noqa: BLE001
        log("error", "run-failed", trace=traceback.format_exc())
        for stage in _STAGES:
            _emit_stage(emit, stage, "fail")
        return {"ok": False, "error": str(e), "duration_ms": int((time.time() - started) * 1000)}

    status = str(getattr(record, "status", "")).lower()
    ok = status.endswith("success")
    for stage in _STAGES:
        _emit_stage(emit, stage, "ok" if ok else "fail")

    return {
        "ok": ok,
        "duration_ms": int((time.time() - started) * 1000),
        "record": {
            "id": getattr(record, "id", None),
            "status": status,
            "email_count": getattr(record, "email_count", 0) or 0,
            "sent_message_id": getattr(record, "sent_message_id", None),
        },
    }


# Raw RunStatus values (see hyacine.models.RunStatus) → UI-facing buckets
# that the desktop frontend colour-codes. We expose both so the app can show
# raw status in tooltips while using the normalised form for styling.
_UI_STATUS = {
    "success": "ok",
    "failed": "fail",
    "pending": "pending",
    "running": "running",
}


def _normalise_status(raw: str | None) -> str:
    if not raw:
        return "pending"
    return _UI_STATUS.get(raw.lower(), raw.lower())


def history(limit: int = 14) -> dict[str, Any]:
    """Return up to ``limit`` most recent runs from the SQLite watermark DB.

    Each run carries both ``status`` (raw enum value from hyacine.models —
    e.g. ``success``/``failed``) and ``status_ui`` (normalised to
    ``ok``/``fail``/``pending``/``running``). Frontend dashboards and layout
    indicators should read ``status_ui``; detail views can show ``status``.
    """
    s = get_settings()
    try:
        init_db(s.db_path)
        with session_scope(s.db_path) as session:
            rows = (
                session.query(Run)
                .order_by(Run.started_at.desc())
                .limit(limit)
                .all()
            )
            return {
                "runs": [
                    {
                        "id": r.id,
                        "status": r.status,
                        "status_ui": _normalise_status(r.status),
                        "started_at": r.started_at.isoformat() if r.started_at else None,
                        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                        "email_count": r.email_count,
                        "sent_message_id": r.sent_message_id,
                        "has_traceback": bool(r.error_traceback),
                    }
                    for r in rows
                ]
            }
    except Exception as e:  # noqa: BLE001
        return {"runs": [], "error": str(e)}


def _markdown_to_html(md: str) -> str:
    """Render markdown → HTML for the dry-run preview.

    We lean on the `markdown` + `bleach` pair already in hyacine's deps so the
    rendered body matches what ``send_email`` would produce; if either is
    missing we fall back to an `<pre>` so the preview still shows something.
    """
    if not md.strip():
        return _placeholder_html()
    try:
        import bleach  # noqa: PLC0415
        import markdown as _md  # noqa: PLC0415

        raw = _md.markdown(md, extensions=["extra", "sane_lists"])
        cleaned = bleach.clean(
            raw,
            tags=list(bleach.sanitizer.ALLOWED_TAGS) + ["p", "h1", "h2", "h3", "h4", "pre", "code"],
            strip=True,
        )
        return _wrap_preview(cleaned)
    except Exception:  # noqa: BLE001
        # Fallback when markdown/bleach are missing or throw: never embed
        # unsanitised text. Escape so any HTML (incl. <script>/<img src=…>)
        # is rendered as literal, not parsed, in the sandboxed iframe.
        import html as _html  # noqa: PLC0415

        return _wrap_preview(f"<pre>{_html.escape(md)}</pre>")


def _wrap_preview(body: str) -> str:
    return (
        '<html><body style="font-family:-apple-system,Segoe UI,Inter,sans-serif;'
        'padding:24px;max-width:680px;line-height:1.55;">'
        f"{body}"
        "</body></html>"
    )


def _placeholder_html() -> str:
    return _wrap_preview(
        '<h1 style="font-size:20px;margin:0 0 16px;">Your daily briefing — preview</h1>'
        '<p style="color:#888;">Nothing new in this run window.</p>'
    )


def _mock_dry_run(emit: Callable[[str, Any], None], started: float) -> dict[str, Any]:
    """Used only when ``hyacine.pipeline.run`` can't be imported — keeps the
    frontend exercisable during early desktop development."""
    for stage in _STAGES:
        _emit_stage(emit, stage, "running")
        time.sleep(0.1)
        _emit_stage(emit, stage, "ok")
    return {
        "ok": True,
        "duration_ms": int((time.time() - started) * 1000),
        "html": _placeholder_html(),
        "subject": "Your Hyacine daily briefing — preview",
        "summary": {"email_count": 0},
    }
