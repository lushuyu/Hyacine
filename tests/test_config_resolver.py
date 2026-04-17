"""Tests for Settings path resolution (no XDG — in-repo defaults only).

Covers:
1. Fresh env → all paths default to in-repo locations
2. HYACINE_DB_PATH env var override takes precedence
3. HYACINE_PROMPT_PATH override works
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hyacine.config import Settings

_PATH_ENV_VARS = [
    "HYACINE_CONFIG_PATH",
    "HYACINE_RULES_PATH",
    "HYACINE_PROMPT_PATH",
    "HYACINE_DB_PATH",
    "HYACINE_AUTH_DIR",
    "HYACINE_LOG_DIR",
]


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _PATH_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_fresh_env_resolves_to_inrepo(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    settings = Settings(_env_file=())  # type: ignore[call-arg]

    assert settings.config_path == Path("./config/config.yaml")
    assert settings.rules_path == Path("./config/rules.yaml")
    assert settings.prompt_path == Path("./prompts/hyacine.md")
    assert settings.db_path == Path("./data/hyacine.db")
    assert settings.auth_dir == Path("./data/auth")
    assert settings.log_dir == Path("./data/logs")
    assert settings.auth_record_path == settings.auth_dir / "auth_record.json"


def test_env_var_overrides_db_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    override = tmp_path / "custom" / "my.db"
    monkeypatch.setenv("HYACINE_DB_PATH", str(override))

    settings = Settings(_env_file=())  # type: ignore[call-arg]
    assert settings.db_path == override


def test_env_var_overrides_prompt_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    override = tmp_path / "prompts" / "custom.md"
    monkeypatch.setenv("HYACINE_PROMPT_PATH", str(override))

    settings = Settings(_env_file=())  # type: ignore[call-arg]
    assert settings.prompt_path == override


def test_auth_record_path_follows_auth_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """auth_record_path is auto-derived from auth_dir when not overridden."""
    _clean_env(monkeypatch)
    auth = tmp_path / "custom_auth"
    monkeypatch.setenv("HYACINE_AUTH_DIR", str(auth))

    settings = Settings(_env_file=())  # type: ignore[call-arg]
    assert settings.auth_dir == auth
    assert settings.auth_record_path == auth / "auth_record.json"
