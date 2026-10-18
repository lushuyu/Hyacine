"""Regression tests for the config IPC handler.

The wizard's /wizard/provider/ step persists its choice by calling
``config.write`` with ``llm_provider`` / ``llm_base_url`` /
``llm_api_format``. An earlier version of ``_SAFE_KEYS`` omitted those
three, so every provider pick failed with

    unknown config key: llm_api_format

Mostly boring allowlist book-keeping, but the failure is silent enough
(users just can't advance past the provider step) that it's worth a
test pinning the happy path.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from hyacine.config import YamlConfig
from hyacine.ipc.handlers import config_h
from hyacine.ipc.protocol import INVALID_PARAMS, RpcError
from hyacine.llm.providers import DEFAULT_CLAUDE_MODEL


@pytest.fixture
def tmp_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every HYACINE_* path override at a fresh tmpdir so tests can
    never accidentally write to the developer's real config.

    Setting ``HYACINE_REPO_ROOT`` alone is *not* enough: ``Settings`` also
    honors per-path overrides like ``HYACINE_CONFIG_PATH`` — either
    exported in the shell or loaded from the repo ``.env`` — and any of
    those would beat the repo-root fallback. We drop them all first, then
    pin ``HYACINE_CONFIG_PATH`` explicitly so there is zero ambiguity
    about which file ``write_config()`` touches.
    """
    (tmp_path / "config").mkdir()
    for leak in (
        "HYACINE_CONFIG_PATH",
        "HYACINE_RULES_PATH",
        "HYACINE_PROMPT_PATH",
        "HYACINE_DB_PATH",
        "HYACINE_AUTH_DIR",
        "HYACINE_LOG_DIR",
        "HYACINE_AUTH_RECORD_PATH",
    ):
        monkeypatch.delenv(leak, raising=False)
    monkeypatch.setenv("HYACINE_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("HYACINE_CONFIG_PATH", str(tmp_path / "config" / "config.yaml"))
    return tmp_path


def test_write_config_accepts_provider_fields(tmp_repo: Path) -> None:
    res = config_h.write_config(
        llm_provider="openai",
        llm_base_url="https://api.openai.com/v1",
        llm_api_format="openai_chat",
        llm_model="gpt-4o-mini",
    )
    assert res["ok"] is True

    got = config_h.read_config()
    assert got["llm_provider"] == "openai"
    assert got["llm_base_url"] == "https://api.openai.com/v1"
    assert got["llm_api_format"] == "openai_chat"
    assert got["llm_model"] == "gpt-4o-mini"


def test_read_config_without_file_reports_default_model(
    tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Settings pane shows this before any config.yaml exists."""
    monkeypatch.delenv("LLM_MODEL", raising=False)  # YamlConfig reads env too
    got = config_h.read_config()
    assert got["exists"] is False
    assert got["llm_model"] == DEFAULT_CLAUDE_MODEL


def test_write_config_still_rejects_unknown_key(tmp_repo: Path) -> None:
    with pytest.raises(RpcError) as e:
        config_h.write_config(nonsense_field="oops")
    assert e.value.code == INVALID_PARAMS
    assert "unknown config key" in str(e.value)


def _config_file(tmp_repo: Path) -> Path:
    return tmp_repo / "config" / "config.yaml"


def test_write_config_rejects_unknown_timezone(tmp_repo: Path) -> None:
    """A typo used to be saved and then failed every run in ZoneInfo()."""
    config_h.write_config(timezone="Asia/Singapore")
    before = _config_file(tmp_repo).read_text(encoding="utf-8")

    with pytest.raises(RpcError) as e:
        config_h.write_config(timezone="shanghai")

    assert e.value.code == INVALID_PARAMS
    assert "unknown timezone: 'shanghai'" in e.value.message
    assert _config_file(tmp_repo).read_text(encoding="utf-8") == before


def test_write_config_rejects_wrongly_typed_value(tmp_repo: Path) -> None:
    """A value YamlConfig can't load used to break config.read and every run."""
    config_h.write_config(recipient_email="me@example.com")

    with pytest.raises(RpcError) as e:
        config_h.write_config(llm_timeout_seconds="10 min")

    assert e.value.code == INVALID_PARAMS
    assert "llm_timeout_seconds" in e.value.message
    got = config_h.read_config()  # still loads
    assert got["recipient_email"] == "me@example.com"


def test_write_config_does_not_recheck_an_untouched_timezone(tmp_repo: Path) -> None:
    """A bad timezone already on disk must not block saving other fields."""
    _config_file(tmp_repo).write_text("timezone: Mars/Olympus\n", encoding="utf-8")

    config_h.write_config(recipient_email="me@example.com")

    assert config_h.read_config()["recipient_email"] == "me@example.com"


def test_write_config_is_atomic(tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_h.write_config(recipient_email="old@example.com")
    before = _config_file(tmp_repo).read_text(encoding="utf-8")

    def _fail_replace(_src: object, _dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(config_h.os, "replace", _fail_replace)
    with pytest.raises(OSError, match="disk full"):
        config_h.write_config(recipient_email="new@example.com")

    assert _config_file(tmp_repo).read_text(encoding="utf-8") == before
    assert sorted(p.name for p in _config_file(tmp_repo).parent.iterdir()) == ["config.yaml"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_write_config_preserves_permissions(tmp_repo: Path) -> None:
    config_h.write_config(recipient_email="old@example.com")
    _config_file(tmp_repo).chmod(0o600)

    config_h.write_config(recipient_email="new@example.com")

    assert stat.S_IMODE(_config_file(tmp_repo).stat().st_mode) == 0o600
    assert config_h.read_config()["recipient_email"] == "new@example.com"


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_write_config_keeps_a_symlinked_config(tmp_repo: Path) -> None:
    real = tmp_repo / "dotfiles" / "hyacine.yaml"
    real.parent.mkdir()
    real.write_text("recipient_email: old@example.com\n", encoding="utf-8")
    _config_file(tmp_repo).symlink_to(real)

    config_h.write_config(recipient_email="new@example.com")

    assert _config_file(tmp_repo).is_symlink()
    assert "new@example.com" in real.read_text(encoding="utf-8")


def test_write_prompt_and_rules_round_trip(
    tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HYACINE_PROMPT_PATH", str(tmp_repo / "prompts" / "hyacine.md"))
    monkeypatch.setenv("HYACINE_RULES_PATH", str(tmp_repo / "config" / "rules.yaml"))

    config_h.write_prompt("# 摘要\n只写要点。\n")
    config_h.write_rules("promote: []\ndemote: []\n")

    assert config_h.read_prompt()["content"] == "# 摘要\n只写要点。\n"
    assert config_h.read_rules()["content"] == "promote: []\ndemote: []\n"
    assert not list(tmp_repo.rglob("*.tmp"))


def test_safe_keys_covers_every_provider_field() -> None:
    """Catches the case where a future refactor adds a new `llm_*` field
    to YamlConfig but forgets to whitelist it — the wizard would silently
    break again."""
    yaml_fields = set(YamlConfig.model_fields)
    provider_fields = {f for f in yaml_fields if f.startswith("llm_")}
    missing = provider_fields - config_h._SAFE_KEYS
    assert not missing, (
        f"YamlConfig has {missing} that the IPC allowlist rejects — "
        f"either add them to _SAFE_KEYS or explicitly carve them out here"
    )
