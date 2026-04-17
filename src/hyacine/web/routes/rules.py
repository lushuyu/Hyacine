"""GET/POST /rules — edit the classification rules yaml.

POST runs through validate_rules_yaml(); 422 on schema violation.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from hyacine.db import ConfigSnapshotRow, session_scope
from hyacine.pipeline.rules import validate_rules_yaml
from hyacine.web.utils import get_settings_from_request

router = APIRouter(prefix="/rules")


@router.get("", response_class=HTMLResponse)
def rules_editor(request: Request) -> HTMLResponse:
    settings = get_settings_from_request(request)
    content = ""
    if settings.rules_path.exists():
        content = settings.rules_path.read_text(encoding="utf-8")
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request, "rules_editor.html", {"content": content, "error": None}
    )


@router.post("", response_model=None)
def save_rules(request: Request, content: str = Form(...)) -> Response:
    settings = get_settings_from_request(request)

    try:
        validate_rules_yaml(content)
    except ValueError as exc:
        templates = request.app.state.templates
        return templates.TemplateResponse(
            request,
            "rules_editor.html",
            {"content": content, "error": str(exc)},
            status_code=422,
        )

    # Persist the new content.
    settings.rules_path.parent.mkdir(parents=True, exist_ok=True)
    settings.rules_path.write_text(content, encoding="utf-8")

    # Insert a config snapshot.
    now = datetime.now(tz=UTC).replace(tzinfo=None)
    with session_scope(settings.db_path, write=True) as session:
        snapshot = ConfigSnapshotRow(kind="rules", created_at=now, content=content)
        session.add(snapshot)

    return RedirectResponse(url="/rules", status_code=303)
