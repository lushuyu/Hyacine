"""Tests for Settings path resolution (no XDG — repo-anchored defaults).

Covers:
1. Fresh env → all paths default to <repo_root>/... (module-relative, not CWD).
2. HYACINE_REPO_ROOT env var re-anchors all default paths.
3. HYACINE_DB_PATH / HYACINE_PROMPT_PATH overrides still take precedence.
4. auth_record_path auto-derives from auth_dir.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hyacine.config import Settings, _default_repo_root

_PATH_ENV_VARS = [
    "HYACINE_CONFIG_PATH",
    "HYACINE_RULES_PATH",
    "HYACINE_PROMPT_PATH",
    "HYACINE_DB_PATH",
    "HYACINE_AUTH_DIR",
    "HYACINE_LOG_DIR",
    "HYACINE_REPO_ROOT",
]


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _PATH_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_fresh_env_resolves_under_repo_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clean_env(monkeypatch)
    settings = Settings(_env_file=())  # type: ignore[call-arg]

    root = _default_repo_root()
    assert settings.config_path == root / "config" / "config.yaml"
    assert settings.rules_path == root / "config" / "rules.yaml"
    assert settings.prompt_path == root / "prompts" / "hyacine.md"
    assert settings.db_path == root / "data" / "hyacine.db"
    assert settings.auth_dir == root / "data" / "auth"
    assert settings.log_dir == root / "data" / "logs"
    assert settings.auth_record_path == settings.auth_dir / "auth_record.json"


def test_paths_are_absolute_even_from_foreign_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running from an unrelated CWD must not rebase default paths to CWD."""
    _clean_env(monkeypatch)
    monkeypatch.chdir(tmp_path)

    settings = Settings(_env_file=())  # type: ignore[call-arg]
    for field in (
        settings.config_path,
        settings.prompt_path,
        settings.db_path,
        settings.auth_dir,
    ):
        assert field.is_absolute(), f"{field!r} should be absolute"
        # And must NOT be anchored at the unrelated CWD.
        assert tmp_path not in field.parents


def test_repo_root_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("HYACINE_REPO_ROOT", str(tmp_path))

    settings = Settings(_env_file=())  # type: ignore[call-arg]
    assert settings.config_path == tmp_path / "config" / "config.yaml"
    assert settings.db_path == tmp_path / "data" / "hyacine.db"
    assert settings.auth_dir == tmp_path / "data" / "auth"


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
