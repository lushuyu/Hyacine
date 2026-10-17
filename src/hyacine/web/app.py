"""FastAPI application factory.

Single-process only (`uvicorn --workers 1`). Multi-worker would violate the
single-writer invariant on SQLite (see db.py).

No auth — LOCAL DEV ONLY. Bind to 127.0.0.1. Do not expose to the network.

Because there is no auth, any page open in the operator's browser could
auto-submit a form to the localhost UI. A middleware rejects cross-site
writes using Sec-Fetch-Site / Origin. Set HYACINE_WEB_ALLOWED_HOSTS
(comma list) to additionally pin the accepted Host headers.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from hyacine.config import get_settings
from hyacine.db import init_db
from hyacine.web.routes import actions, dashboard, prompt, rules, runs

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# "same-site" is deliberately excluded: another port on localhost is same-site.
_TRUSTED_FETCH_SITES = frozenset({"same-origin", "none"})
_LOOPBACK_HOSTS = ("127.0.0.1", "localhost")


def _is_cross_site(request: Request) -> bool:
    """True when the browser says the request came from another origin.

    Prefers Sec-Fetch-Site; falls back to comparing Origin with Host for
    browsers that don't send it. Requests carrying neither header (curl,
    scripts, TestClient) are not browser-initiated and pass.
    """
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site is not None:
        return fetch_site.lower() not in _TRUSTED_FETCH_SITES
    origin = request.headers.get("origin")
    if origin is None:
        return False
    if origin == "null":  # sandboxed iframes, file://, some redirects
        return True
    host = request.headers.get("host", "")
    return urlsplit(origin).netloc.lower() != host.lower()


def _allowed_hosts_from_env() -> list[str] | None:
    """Parse HYACINE_WEB_ALLOWED_HOSTS; None (no Host pinning) when unset or blank."""
    raw = os.environ.get("HYACINE_WEB_ALLOWED_HOSTS", "")
    hosts = [h.strip().lower() for h in raw.split(",") if h.strip()]
    if not hosts:
        return None
    return hosts + [h for h in _LOOPBACK_HOSTS if h not in hosts]


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

    # CSRF guard: the prompt is used verbatim as the LLM system prompt, so a
    # forged POST from another site must never reach the write endpoints.
    @app.middleware("http")
    async def reject_cross_site_writes(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method not in _SAFE_METHODS and _is_cross_site(request):
            return PlainTextResponse("Cross-site request blocked", status_code=403)
        return await call_next(request)

    # Opt-in Host pinning (DNS-rebinding defence). Off by default so tailnet
    # access via http://<host>.<tailnet>:8765 keeps working out of the box.
    allowed_hosts = _allowed_hosts_from_env()
    if allowed_hosts is not None:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    return app


app = create_app()
