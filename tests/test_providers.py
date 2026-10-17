"""Default-model wiring for the provider presets and the probes that use them.

Every "which Claude model?" fallback is meant to resolve to
:data:`hyacine.llm.providers.DEFAULT_CLAUDE_MODEL`. These tests pin each
copy of that default — the presets, ``YamlConfig`` (which keeps a literal to
avoid importing the LLM layer), the shipped YAML files, the desktop mirrors
and the IPC probe fallbacks — so a future bump can't miss one.

No network or real ``claude`` binary: ``subprocess.run`` and ``httpx.post``
are monkeypatched.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from hyacine.config import YamlConfig
from hyacine.ipc.handlers import connectivity_h, providers_h
from hyacine.llm.providers import DEFAULT_CLAUDE_MODEL, by_id, default_provider, resolve

_REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pid", ["claude-code-oauth", "anthropic-console"])
def test_claude_presets_default_to_default_model(pid: str) -> None:
    p = by_id(pid)
    assert p is not None
    assert p.default_model == DEFAULT_CLAUDE_MODEL
    # Default first, so the dropdown opens on it.
    assert p.models[0] == DEFAULT_CLAUDE_MODEL


def test_cli_preset_offers_full_ids_and_aliases() -> None:
    p = by_id("claude-code-oauth")
    assert p is not None
    assert p.models == (
        DEFAULT_CLAUDE_MODEL,
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
        "opus",
        "sonnet",
        "haiku",
    )


def test_console_preset_only_lists_full_ids() -> None:
    """The Messages API rejects CLI aliases like "sonnet"."""
    p = by_id("anthropic-console")
    assert p is not None
    assert p.models == (DEFAULT_CLAUDE_MODEL, "claude-sonnet-5-5", "claude-haiku-5-5")


def test_resolve_without_model_uses_default_model() -> None:
    assert resolve().default_model == DEFAULT_CLAUDE_MODEL
    assert default_provider().default_model == DEFAULT_CLAUDE_MODEL
    assert resolve(provider_id="anthropic-console").default_model == DEFAULT_CLAUDE_MODEL


# ---------------------------------------------------------------------------
# Other copies of the default
# ---------------------------------------------------------------------------

def test_yamlconfig_default_matches_constant() -> None:
    """config.py keeps a literal (importing the constant would drag httpx and
    every LLM backend into each config import); this guards against drift."""
    assert YamlConfig.model_fields["llm_model"].default == DEFAULT_CLAUDE_MODEL


@pytest.mark.parametrize(
    "rel",
    ["config/defaults.yaml", "examples/alice/config/config.yaml"],
)
def test_shipped_yaml_uses_default_model(rel: str) -> None:
    data = yaml.safe_load((_REPO_ROOT / rel).read_text(encoding="utf-8"))
    assert data["llm_model"] == DEFAULT_CLAUDE_MODEL


@pytest.mark.parametrize(
    ("rel", "needle"),
    [
        ("desktop/src/lib/provider-presets.ts", f"DEFAULT_CLAUDE_MODEL = '{DEFAULT_CLAUDE_MODEL}'"),
        ("desktop/src-tauri/src/commands/secrets.rs", f'"{DEFAULT_CLAUDE_MODEL}".into()'),
    ],
)
def test_desktop_mirrors_default_model(rel: str, needle: str) -> None:
    assert needle in (_REPO_ROOT / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# providers.test probes
# ---------------------------------------------------------------------------

def _fake_cli_run(calls: list[dict[str, Any]]) -> Any:
    def _run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append({"argv": argv, **kwargs})
        return subprocess.CompletedProcess(argv, 0, stdout=b"pong", stderr=b"")

    return _run


def test_cli_probe_detaches_stdin_and_defaults_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """The sidecar's stdin is the JSON-RPC channel; `claude -p` must not
    inherit it (it would block on stdin and could eat RPC frames)."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "hyacine.llm.claude_code.resolve_claude_bin", lambda _env: "/usr/bin/claude"
    )
    monkeypatch.setattr(providers_h.subprocess, "run", _fake_cli_run(calls))

    res = providers_h._probe_anthropic_cli(api_key="", model="")

    assert res["status"] == "ok"
    assert len(calls) == 1
    assert calls[0]["stdin"] is subprocess.DEVNULL
    argv = calls[0]["argv"]
    assert argv[argv.index("--model") + 1] == DEFAULT_CLAUDE_MODEL


def test_cli_probe_via_test_uses_preset_default(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "hyacine.llm.claude_code.resolve_claude_bin", lambda _env: "/usr/bin/claude"
    )
    monkeypatch.setattr(providers_h.subprocess, "run", _fake_cli_run(calls))

    res = providers_h.test(provider_id="claude-code-oauth")

    assert res["status"] == "ok"
    argv = calls[0]["argv"]
    assert argv[argv.index("--model") + 1] == DEFAULT_CLAUDE_MODEL


def test_http_probe_defaults_model(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _post(url: str, **kwargs: Any) -> httpx.Response:
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return httpx.Response(200, json={})

    monkeypatch.setattr(providers_h.httpx, "post", _post)

    res = providers_h._probe_anthropic_http("https://api.anthropic.com", "sk-ant-api-x", "")

    assert res["status"] == "ok"
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["json"]["model"] == DEFAULT_CLAUDE_MODEL


# ---------------------------------------------------------------------------
# connectivity.claude fallback
# ---------------------------------------------------------------------------

def test_connectivity_default_model_when_config_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connectivity_h, "load_yaml_config", lambda _p: YamlConfig(llm_model=""))
    assert connectivity_h._default_claude_model() == DEFAULT_CLAUDE_MODEL


def test_connectivity_default_model_when_config_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(_p: Path) -> YamlConfig:
        raise OSError("unreadable")

    monkeypatch.setattr(connectivity_h, "load_yaml_config", _boom)
    assert connectivity_h._default_claude_model() == DEFAULT_CLAUDE_MODEL


def test_connectivity_prefers_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        connectivity_h, "load_yaml_config", lambda _p: YamlConfig(llm_model="claude-haiku-5-5")
    )
    assert connectivity_h._default_claude_model() == "claude-haiku-5-5"
