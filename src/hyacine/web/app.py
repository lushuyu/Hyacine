"""FastAPI application factory.

Single-process only (`uvicorn --workers 1`). Multi-worker would violate the
single-writer invariant on SQLite (see db.py).

No auth — LOCAL DEV ONLY. Bind to 127.0.0.1. Do not expose to the network.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from hyacine.config import get_settings
from hyacine.db import init_db
from hyacine.web.routes import actions, dashboard, prompt, rules, runs


def create_app(templates_dir: Path | None = None) -> FastAPI:
    """Build the app: mount static, register routes, wire Jinja env."""

    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        init_db(settings.db_path)
        yield

    app = FastAPI(title="hyacine", lifespan=lifespan)

    # Set up Jinja2 templates — callers can override the directory for tests.
    tdir = templates_dir or Path(__file__).parent / "templates"
    app.state.templates = Jinja2Templates(directory=str(tdir))
    app.state.settings = settings

    # Mount static files if the directory has content.
    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir() and any(static_dir.iterdir()):
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Include routers.
    app.include_router(dashboard.router)
    app.include_router(runs.router)
    app.include_router(actions.router)
    app.include_router(prompt.router)
    app.include_router(rules.router)

    return app


app = create_app()
