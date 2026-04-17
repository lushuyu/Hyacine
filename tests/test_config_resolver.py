"""Tests for Settings XDG path resolver.

Covers:
1. Fresh env (no files anywhere) → all paths resolve to XDG defaults
2. Legacy in-repo files exist → paths resolve to legacy
3. XDG files exist → paths resolve to XDG (XDG wins over legacy)
4. HYACINE_DB_PATH env var overrides everything
5. XDG_CONFIG_HOME env var respected
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hyacine.config import Settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(monkeypatch: pytest.MonkeyPatch, tmp_home: Path) -> Settings:
    """Build a Settings instance with home() pointing at tmp_home.

    Passes ``_env_file=()`` to suppress loading of any .env or hyacine.env
    files from the repo or the real filesystem, so only real env vars (after
    monkeypatching) affect the result.
    """
    monkeypatch.setattr(Path, "home", lambda: tmp_home)
    # Clear any env-var overrides that could interfere
    for var in [
        "HYACINE_CONFIG_PATH",
        "HYACINE_RULES_PATH",
        "HYACINE_PROMPT_PATH",
        "HYACINE_DB_PATH",
        "HYACINE_AUTH_DIR",
        "HYACINE_LOG_DIR",
        "XDG_CONFIG_HOME",
        "XDG_STATE_HOME",
        "XDG_CACHE_HOME",
    ]:
        monkeypatch.delenv(var, raising=False)
    # _env_file=() suppresses .env / hyacine.env file loading
    return Settings(_env_file=())  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Test 1: Fresh env — all paths resolve to XDG defaults
# ---------------------------------------------------------------------------


def test_fresh_env_resolves_to_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With no existing files anywhere, every path should be under ~/.config/hyacine
    or ~/.local/state/hyacine (XDG defaults)."""
    tmp_home = tmp_path / "home"
    tmp_home.mkdir()

    # chdir to an empty dir so legacy "./config/..." paths don't exist
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.chdir(empty_dir)

    settings = _make_settings(monkeypatch, tmp_home)

    xdg_cfg = tmp_home / ".config" / "hyacine"
    xdg_state = tmp_home / ".local" / "state" / "hyacine"

    assert settings.config_dir == xdg_cfg
    assert settings.state_dir == xdg_state
    assert settings.config_path == xdg_cfg / "config.yaml"
    assert settings.rules_path == xdg_cfg / "rules.yaml"
    assert settings.prompt_path == xdg_cfg / "prompts" / "briefing.md"
    assert settings.db_path == xdg_state / "hyacine.db"
    assert settings.auth_dir == xdg_state / "auth"
    assert settings.log_dir == xdg_state / "logs"
    assert settings.auth_record_path == settings.auth_dir / "auth_record.json"


# ---------------------------------------------------------------------------
# Test 2: Legacy in-repo files exist → resolver falls back to legacy
# ---------------------------------------------------------------------------


def test_legacy_files_resolve_to_legacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When only legacy in-repo paths exist, resolver should use them."""
    tmp_home = tmp_path / "home"
    tmp_home.mkdir()

    # Create legacy in-repo paths (as if user is running from repo root)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text("recipient_email: legacy@example.com\n")
    (tmp_path / "config" / "rules.yaml").write_text("rules: []\n")
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "briefing.md").write_text("# Legacy prompt\n")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "briefing.db").write_bytes(b"")
    (tmp_path / "data" / "logs").mkdir()

    monkeypatch.setattr(Path, "home", lambda: tmp_home)
    for var in [
        "HYACINE_CONFIG_PATH",
        "HYACINE_RULES_PATH",
        "HYACINE_PROMPT_PATH",
        "HYACINE_DB_PATH",
        "HYACINE_AUTH_DIR",
        "HYACINE_LOG_DIR",
        "XDG_CONFIG_HOME",
        "XDG_STATE_HOME",
    ]:
        monkeypatch.delenv(var, raising=False)

    # Change cwd to tmp_path so relative "./config/..." paths resolve correctly
    monkeypatch.chdir(tmp_path)

    # _env_file=() suppresses .env file loading
    settings = Settings(_env_file=())  # type: ignore[call-arg]

    assert settings.config_path == Path("./config/config.yaml")
    assert settings.rules_path == Path("./config/rules.yaml")
    assert settings.prompt_path == Path("./prompts/briefing.md")
    assert settings.db_path == Path("./data/briefing.db")
    assert settings.log_dir == Path("./data/logs")


# ---------------------------------------------------------------------------
# Test 3: XDG files exist → XDG wins over legacy
# ---------------------------------------------------------------------------


def test_xdg_wins_over_legacy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When BOTH XDG and legacy paths exist, XDG should be selected."""
    tmp_home = tmp_path / "home"
    tmp_home.mkdir()

    # Create XDG paths
    xdg_cfg = tmp_home / ".config" / "hyacine"
    xdg_state = tmp_home / ".local" / "state" / "hyacine"
    (xdg_cfg / "prompts").mkdir(parents=True)
    (xdg_state / "auth").mkdir(parents=True)
    (xdg_state / "logs").mkdir(parents=True)
    (xdg_cfg / "config.yaml").write_text("recipient_email: xdg@example.com\n")
    (xdg_cfg / "rules.yaml").write_text("rules: []\n")
    (xdg_cfg / "prompts" / "briefing.md").write_text("# XDG prompt\n")
    (xdg_state / "hyacine.db").write_bytes(b"")

    # Also create legacy in-repo paths
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text("recipient_email: legacy@example.com\n")
    (tmp_path / "config" / "rules.yaml").write_text("rules: []\n")
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "briefing.md").write_text("# Legacy prompt\n")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "hyacine.db").write_bytes(b"")

    monkeypatch.setattr(Path, "home", lambda: tmp_home)
    for var in [
        "HYACINE_CONFIG_PATH",
        "HYACINE_RULES_PATH",
        "HYACINE_PROMPT_PATH",
        "HYACINE_DB_PATH",
        "HYACINE_AUTH_DIR",
        "HYACINE_LOG_DIR",
        "XDG_CONFIG_HOME",
        "XDG_STATE_HOME",
    ]:
        monkeypatch.delenv(var, raising=False)

    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=())  # type: ignore[call-arg]

    assert settings.config_path == xdg_cfg / "config.yaml"
    assert settings.rules_path == xdg_cfg / "rules.yaml"
    assert settings.prompt_path == xdg_cfg / "prompts" / "briefing.md"
    assert settings.db_path == xdg_state / "hyacine.db"


# ---------------------------------------------------------------------------
# Test 4: HYACINE_DB_PATH env var overrides everything
# ---------------------------------------------------------------------------


def test_env_var_overrides_xdg_and_legacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HYACINE_DB_PATH env var must take precedence over all path heuristics."""
    tmp_home = tmp_path / "home"
    tmp_home.mkdir()

    override_db = tmp_path / "custom" / "my.db"

    monkeypatch.setattr(Path, "home", lambda: tmp_home)
    monkeypatch.setenv("HYACINE_DB_PATH", str(override_db))
    for var in [
        "HYACINE_CONFIG_PATH",
        "HYACINE_RULES_PATH",
        "HYACINE_PROMPT_PATH",
        "HYACINE_AUTH_DIR",
        "HYACINE_LOG_DIR",
        "XDG_CONFIG_HOME",
        "XDG_STATE_HOME",
    ]:
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=())  # type: ignore[call-arg]

    assert settings.db_path == override_db


# ---------------------------------------------------------------------------
# Test 5: XDG_CONFIG_HOME env var is respected
# ---------------------------------------------------------------------------


def test_xdg_config_home_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """XDG_CONFIG_HOME env var must redirect the config_dir base."""
    tmp_home = tmp_path / "home"
    tmp_home.mkdir()

    custom_xdg_config = tmp_path / "custom_xdg_config"
    custom_xdg_config.mkdir()

    # chdir to empty dir so legacy "./config/..." paths don't exist
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.chdir(empty_dir)

    monkeypatch.setattr(Path, "home", lambda: tmp_home)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(custom_xdg_config))
    for var in [
        "HYACINE_CONFIG_PATH",
        "HYACINE_RULES_PATH",
        "HYACINE_PROMPT_PATH",
        "HYACINE_DB_PATH",
        "HYACINE_AUTH_DIR",
        "HYACINE_LOG_DIR",
        "XDG_STATE_HOME",
    ]:
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=())  # type: ignore[call-arg]

    expected_cfg_dir = custom_xdg_config / "hyacine"
    assert settings.config_dir == expected_cfg_dir
    assert settings.config_path == expected_cfg_dir / "config.yaml"
    assert settings.rules_path == expected_cfg_dir / "rules.yaml"
    assert settings.prompt_path == expected_cfg_dir / "prompts" / "briefing.md"
