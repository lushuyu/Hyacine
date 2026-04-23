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

from pathlib import Path

import pytest

from hyacine.config import YamlConfig
from hyacine.ipc.handlers import config_h
from hyacine.ipc.protocol import INVALID_PARAMS, RpcError


@pytest.fixture
def tmp_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point HYACINE_REPO_ROOT at an empty tmpdir so each test gets a fresh
    config.yaml without touching the repo or the user's real config."""
    (tmp_path / "config").mkdir()
    monkeypatch.setenv("HYACINE_REPO_ROOT", str(tmp_path))
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


def test_write_config_still_rejects_unknown_key(tmp_repo: Path) -> None:
    with pytest.raises(RpcError) as e:
        config_h.write_config(nonsense_field="oops")
    assert e.value.code == INVALID_PARAMS
    assert "unknown config key" in str(e.value)


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
