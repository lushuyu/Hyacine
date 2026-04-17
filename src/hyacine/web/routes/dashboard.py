"""GET / — list recent runs."""
from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from hyacine.config import YamlConfig, load_yaml_config
from hyacine.db import BriefingRun, session_scope
from hyacine.web.utils import get_settings_from_request

router = APIRouter()


def _fmt_dt(dt: datetime | None, tz: ZoneInfo) -> str:
    """Format a datetime in the configured timezone as 'HH:MM:SS on Mon DD'."""
    if dt is None:
        return "\u2014"
    local = dt.replace(tzinfo=UTC).astimezone(tz)
    return local.strftime("%H:%M:%S on %b %d")


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    settings = get_settings_from_request(request)
    try:
        yaml_cfg = load_yaml_config(settings.config_path)
    except Exception:
        yaml_cfg = YamlConfig()
    tz = ZoneInfo(yaml_cfg.timezone)

    with session_scope(settings.db_path) as session:
        rows = session.execute(
            select(BriefingRun).order_by(BriefingRun.started_at.desc()).limit(50)
        ).scalars().all()

    runs = [
        {
            "id": r.id,
            "started_at": _fmt_dt(r.started_at, tz),
            "finished_at": _fmt_dt(r.finished_at, tz),
            "status": r.status,
            "window_from": _fmt_dt(r.window_from, tz),
            "window_to": _fmt_dt(r.window_to, tz),
            "email_count": r.email_count,
        }
        for r in rows
    ]

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request, "dashboard.html", {"runs": runs}
    )
