"""Shared helpers for web routes."""
from __future__ import annotations

from fastapi import Request

from hyacine.config import Settings, get_settings


def get_settings_from_request(request: Request) -> Settings:
    """Retrieve the Settings instance stored in app.state, with fallback."""
    state = request.app.state
    if hasattr(state, "settings"):
        settings: Settings = state.settings
        return settings
    return get_settings()
