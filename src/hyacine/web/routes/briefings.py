"""GET /briefings/{id} — single run detail view."""
from __future__ import annotations

import bleach
import markdown
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from hyacine.db import BriefingRun, session_scope
from hyacine.web.utils import get_settings_from_request

router = APIRouter(prefix="/briefings")

# Tags/attrs that are safe for display in HTML.
_ALLOWED_TAGS = [
    "p", "br", "strong", "em", "b", "i", "u", "s",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "dl", "dt", "dd",
    "blockquote", "pre", "code", "hr",
    "table", "thead", "tbody", "tr", "th", "td",
    "a", "img", "span", "div",
]
_ALLOWED_ATTRS: dict[str, list[str]] = {
    "a": ["href", "title", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
}


def _render_markdown(text: str) -> str:
    """Convert markdown to sanitized HTML."""
    try:
        from hyacine.graph.send import render_html_body
        return render_html_body(text)
    except NotImplementedError:
        pass
    raw = markdown.markdown(text, extensions=["extra", "tables", "fenced_code"])
    return bleach.clean(raw, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS, strip=False)


@router.get("/{run_id}", response_class=HTMLResponse)
def briefing_detail(run_id: int, request: Request) -> HTMLResponse:
    settings = get_settings_from_request(request)

    with session_scope(settings.db_path) as session:
        row = session.execute(
            select(BriefingRun).where(BriefingRun.id == run_id)
        ).scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    rendered_html = ""
    if row.briefing_markdown:
        rendered_html = _render_markdown(row.briefing_markdown)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "briefing_detail.html",
        {"run": row, "rendered_html": rendered_html},
    )
