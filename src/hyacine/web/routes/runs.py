"""GET /runs/{id} — single run detail view."""
from __future__ import annotations

import bleach
import markdown
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from hyacine.db import Run, session_scope
from hyacine.web.utils import get_settings_from_request

router = APIRouter(prefix="/runs")

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
    """Convert markdown to a sanitized, design-styled HTML fragment.

    Uses ``render_html_fragment`` (no ``<!doctype html>`` wrapper) so
    the result embeds cleanly inside the run-detail Jinja template's
    ``<div>`` container — wrapping the email shell here would nest a
    full document inside another page. Falls back to a plain
    bleach-cleaned render only if the import itself fails (e.g. an
    in-tree refactor temporarily breaks ``hyacine.graph.send``); the
    fallback is module-import-only and won't mask runtime errors.
    """
    try:
        from hyacine.graph.send import render_html_fragment
    except ImportError:
        raw = markdown.markdown(text, extensions=["extra", "tables", "fenced_code"])
        return bleach.clean(raw, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS, strip=False)
    return render_html_fragment(text)


@router.get("/{run_id}", response_class=HTMLResponse)
def run_detail(run_id: int, request: Request) -> HTMLResponse:
    settings = get_settings_from_request(request)

    with session_scope(settings.db_path) as session:
        row = session.execute(
            select(Run).where(Run.id == run_id)
        ).scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    rendered_html = ""
    if row.markdown:
        rendered_html = _render_markdown(row.markdown)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "run_detail.html",
        {"run": row, "rendered_html": rendered_html},
    )
