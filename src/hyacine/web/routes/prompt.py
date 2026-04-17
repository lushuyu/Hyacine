"""GET/POST /prompt — edit the hyacine system prompt.

POST validates with jinja2.Environment().parse() before persisting + snapshot.
Returns 422 with line-number hints on syntax failure.
"""
from __future__ import annotations

from datetime import UTC, datetime

import jinja2
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from hyacine.db import ConfigSnapshotRow, session_scope
from hyacine.web.utils import get_settings_from_request

router = APIRouter(prefix="/prompt")


@router.get("", response_class=HTMLResponse)
def prompt_editor(request: Request) -> HTMLResponse:
    settings = get_settings_from_request(request)
    content = ""
    if settings.prompt_path.exists():
        content = settings.prompt_path.read_text(encoding="utf-8")
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request, "prompt_editor.html", {"content": content, "error": None}
    )


@router.post("", response_model=None)
def save_prompt(request: Request, content: str = Form(...)) -> Response:
    settings = get_settings_from_request(request)

    # Validate Jinja2 syntax.
    try:
        jinja2.Environment().parse(content)
    except jinja2.TemplateSyntaxError as exc:
        templates = request.app.state.templates
        return templates.TemplateResponse(
            request,
            "prompt_editor.html",
            {"content": content, "error": str(exc)},
            status_code=422,
        )

    # Persist the new content.
    settings.prompt_path.parent.mkdir(parents=True, exist_ok=True)
    settings.prompt_path.write_text(content, encoding="utf-8")

    # Insert a config snapshot.
    now = datetime.now(tz=UTC).replace(tzinfo=None)
    with session_scope(settings.db_path, write=True) as session:
        snapshot = ConfigSnapshotRow(kind="prompt", created_at=now, content=content)
        session.add(snapshot)

    return RedirectResponse(url="/prompt", status_code=303)
