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

import os
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from hyacine.config import YamlConfig
from hyacine.ipc.handlers import providers_h
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

@pytest.fixture(autouse=True)
def _clean_claude_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # The probe env now goes through claude_code.build_env; keep the
    # developer's own shell (possibly itself inside Claude Code) out of it.
    for var in (
        "HYACINE_CLAUDE_EFFORT",
        "HYACINE_CLAUDE_SAFE_MODE",
        "CLAUDE_CODE_EFFORT_LEVEL",
        "CLAUDE_CODE_SAFE_MODE",
    ):
        monkeypatch.delenv(var, raising=False)


def _fake_cli_run(calls: list[dict[str, Any]]) -> Any:
    def _run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        cwd = kwargs.get("cwd")
        calls.append(
            {
                "argv": argv,
                **kwargs,
                "cwd_existed": cwd is not None and Path(cwd).is_dir(),
                "cwd_empty": cwd is not None and not any(Path(cwd).iterdir()),
            }
        )
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


def test_cli_probe_runs_like_the_daily_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same env rules as claude_code.summarize (build_env) and an empty temp cwd."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "hyacine.llm.claude_code.resolve_claude_bin", lambda _env: "/usr/bin/claude"
    )
    monkeypatch.setattr(providers_h.subprocess, "run", _fake_cli_run(calls))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-should-not-leak")

    res = providers_h._probe_anthropic_cli(api_key=" oauth-tok ", model="")

    assert res["status"] == "ok"
    call = calls[0]
    env = call["env"]
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth-tok"
    assert env["CLAUDE_CODE_SAFE_MODE"] == "1"
    assert env["CLAUDE_CODE_EFFORT_LEVEL"] == "high"
    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env

    cwd = Path(call["cwd"])
    assert cwd.name.startswith("hyacine-claude-")
    assert cwd != Path.cwd()
    assert call["cwd_existed"] and call["cwd_empty"]
    assert not cwd.exists(), "temp cwd should be cleaned up"
    assert call["stdin"] is subprocess.DEVNULL
    assert call["timeout"] == 30


def test_cli_probe_invalid_effort_fails_without_spawning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("must not get this far")

    monkeypatch.setattr("hyacine.llm.claude_code.resolve_claude_bin", _boom)
    monkeypatch.setattr(providers_h.subprocess, "run", _boom)
    monkeypatch.setenv("HYACINE_CLAUDE_EFFORT", "ultra")

    res = providers_h.test(provider_id="claude-code-oauth")

    assert res["kind"] == "providers.test"
    assert res["status"] == "fail"
    assert res["detail"].startswith("HYACINE_CLAUDE_EFFORT='ultra' is not one of")


def test_cli_probe_unexecutable_binary_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_a: Any, **_kw: Any) -> Any:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(
        "hyacine.llm.claude_code.resolve_claude_bin", lambda _env: "/usr/bin/claude"
    )
    monkeypatch.setattr(providers_h.subprocess, "run", _raise)

    res = providers_h._probe_anthropic_cli(api_key="", model="")

    assert res["status"] == "fail"
    assert "could not execute `claude` at '/usr/bin/claude'" in res["detail"]


def test_cli_probe_without_flag_uses_the_sidecar_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "hyacine.llm.claude_code.resolve_claude_bin", lambda _env: "/usr/bin/claude"
    )
    monkeypatch.setattr(providers_h.subprocess, "run", _fake_cli_run(calls))
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sidecar-tok")

    res = providers_h.test(provider_id="claude-code-oauth")

    assert res["status"] == "ok"
    assert calls[0]["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "sidecar-tok"


def test_cli_login_probe_runs_without_any_oauth_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replacing a stored token with `claude login`: the test must not pass on
    the token that Continue is about to delete (still in the sidecar env)."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "hyacine.llm.claude_code.resolve_claude_bin", lambda _env: "/usr/bin/claude"
    )
    monkeypatch.setattr(providers_h.subprocess, "run", _fake_cli_run(calls))
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sidecar-tok")
    monkeypatch.setenv("HYACINE_CLAUDE_CODE_OAUTH_TOKEN", "alias-tok")

    res = providers_h.test(
        provider_id="claude-code-oauth", api_key="typed-tok", use_cli_login=True
    )

    assert res["status"] == "ok"
    env = calls[0]["env"]
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env
    assert "HYACINE_CLAUDE_CODE_OAUTH_TOKEN" not in env
    # Same build_env rules as any other CLI probe.
    assert env["CLAUDE_CODE_SAFE_MODE"] == "1"
    # Only the child's env changes, not the sidecar's.
    assert os.environ["CLAUDE_CODE_OAUTH_TOKEN"] == "sidecar-tok"
    assert os.environ["HYACINE_CLAUDE_CODE_OAUTH_TOKEN"] == "alias-tok"


def test_cli_login_flag_does_not_affect_key_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _post(url: str, **kwargs: Any) -> httpx.Response:
        captured["headers"] = kwargs["headers"]
        return httpx.Response(200, json={})

    monkeypatch.setattr(providers_h.httpx, "post", _post)

    res = providers_h.test(
        provider_id="anthropic-console", api_key="sk-ant-api-x", use_cli_login=True
    )

    assert res["status"] == "ok"
    assert captured["headers"]["x-api-key"] == "sk-ant-api-x"


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
# providers.test key fallback: HYACINE_LLM_API_KEY only for the active endpoint
# ---------------------------------------------------------------------------

_ACTIVE_KEY = "sk-ant-api03-ACTIVE-CONSOLE-KEY"


@pytest.fixture
def active_console(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Sidecar state the Rust parent leaves behind when Anthropic Console is
    active: config.yaml names it and HYACINE_LLM_API_KEY holds its key."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("llm_provider: anthropic-console\n", encoding="utf-8")
    monkeypatch.setenv("HYACINE_CONFIG_PATH", str(cfg))
    # YamlConfig also reads these from the environment.
    for var in ("LLM_PROVIDER", "LLM_API_FORMAT", "LLM_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("HYACINE_LLM_API_KEY", _ACTIVE_KEY)
    return cfg


def _capture_post(calls: list[dict[str, Any]]) -> Any:
    def _post(url: str, **kwargs: Any) -> httpx.Response:
        calls.append({"url": url, **kwargs})
        return httpx.Response(200, json={})

    return _post


def test_stored_key_is_used_for_the_active_provider(
    active_console: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(providers_h.httpx, "post", _capture_post(calls))

    res = providers_h.test(provider_id="anthropic-console")

    assert res["status"] == "ok"
    assert calls[0]["url"] == "https://api.anthropic.com/v1/messages"
    assert calls[0]["headers"]["x-api-key"] == _ACTIVE_KEY


def test_active_key_is_not_sent_to_another_vendor(
    active_console: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(providers_h.httpx, "post", _capture_post(calls))

    res = providers_h.test(provider_id="deepseek-anthropic")

    assert res["status"] == "fail"
    assert "requires an api_key" in res["detail"]
    assert "no key is stored for this provider" in res["detail"]
    assert calls == []


def test_active_key_is_not_sent_to_a_local_server(
    active_console: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(providers_h.httpx, "post", _capture_post(calls))

    res = providers_h.test(provider_id="ollama-local")

    assert res["status"] == "ok"
    assert calls[0]["url"] == "http://localhost:11434/v1/chat/completions"
    assert "authorization" not in calls[0]["headers"]


def test_active_key_never_becomes_the_cli_oauth_token(
    active_console: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It would override the user's `claude login` and fail the probe."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "hyacine.llm.claude_code.resolve_claude_bin", lambda _env: "/usr/bin/claude"
    )
    monkeypatch.setattr(providers_h.subprocess, "run", _fake_cli_run(calls))

    res = providers_h.test(provider_id="claude-code-oauth")

    assert res["status"] == "ok"
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in calls[0]["env"]


def test_explicit_key_is_always_used(
    active_console: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(providers_h.httpx, "post", _capture_post(calls))

    res = providers_h.test(provider_id="deepseek-anthropic", api_key="sk-deepseek")

    assert res["status"] == "ok"
    assert calls[0]["url"] == "https://api.deepseek.com/anthropic/v1/messages"
    assert calls[0]["headers"]["x-api-key"] == "sk-deepseek"


def test_custom_endpoint_gets_the_key_only_at_the_configured_url(
    active_console: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    active_console.write_text(
        "llm_provider: ''\n"
        "llm_api_format: openai_chat\n"
        "llm_base_url: https://llm.example.com/v1\n",
        encoding="utf-8",
    )
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(providers_h.httpx, "post", _capture_post(calls))

    same = providers_h.test(api_format="openai_chat", base_url="https://llm.example.com/v1/")
    other = providers_h.test(api_format="openai_chat", base_url="https://other.example.net/v1")

    assert same["status"] == "ok"
    assert calls[0]["headers"]["authorization"] == f"Bearer {_ACTIVE_KEY}"
    assert other["status"] == "fail"
    assert len(calls) == 1


def test_unreadable_config_means_no_fallback(
    active_console: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    active_console.write_text("llm_timeout_seconds: soon\n", encoding="utf-8")
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(providers_h.httpx, "post", _capture_post(calls))

    res = providers_h.test(provider_id="anthropic-console")

    assert res["status"] == "fail"
    assert calls == []
