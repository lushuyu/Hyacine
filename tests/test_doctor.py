"""Tests for scripts/doctor.py."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hyacine.llm.providers import Provider, by_id, resolve

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import doctor  # noqa: E402
from doctor import (  # noqa: E402
    FAIL,
    PASS,
    WARN,
    _non_cli_provider,
    check_auth_record,
    check_claude_cli,
    check_config_yaml,
    check_conflicting_keys,
    check_db,
    check_env_file,
    check_llm_api_key,
    check_oauth_token,
    check_prompt_md,
    check_rules_yaml,
    run_checks,
)


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point HOME at an empty dir so the developer's ~/.claude login is invisible."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


def _make_file(path: Path, content: str = "# content\n", mode: int = 0o600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)
    return path


# ---------------------------------------------------------------------------
# check_env_file
# ---------------------------------------------------------------------------

def test_env_file_missing(tmp_path: Path) -> None:
    status, _label, _detail = check_env_file(tmp_path / ".env")
    assert status == FAIL


def test_env_file_wrong_mode(tmp_path: Path) -> None:
    f = _make_file(tmp_path / ".env", mode=0o644)
    status, _label, detail = check_env_file(f)
    assert status == WARN
    assert "644" in detail


def test_env_file_correct(tmp_path: Path) -> None:
    f = _make_file(tmp_path / ".env", mode=0o600)
    status, _label, _detail = check_env_file(f)
    assert status == PASS


# ---------------------------------------------------------------------------
# check_oauth_token
# ---------------------------------------------------------------------------

def test_oauth_token_missing(monkeypatch: pytest.MonkeyPatch, isolated_home: Path) -> None:
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    status, _label, detail = check_oauth_token()
    assert status == FAIL
    assert "not set" in detail.lower()


def test_oauth_token_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-replace-me")
    status, _label, detail = check_oauth_token()
    assert status == FAIL
    assert "placeholder" in detail.lower()


def test_oauth_token_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok-valid-token-value-12345")
    status, _label, _detail = check_oauth_token()
    assert status == PASS


def test_oauth_token_missing_reports_env_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    """When env_file is passed, the FAIL detail must mention that resolved path."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    env_file = tmp_path / "custom" / ".env"
    status, _label, detail = check_oauth_token(env_file)
    assert status == FAIL
    assert str(env_file) in detail


def test_oauth_token_read_from_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    """A token that only lives in .env (systemd's EnvironmentFile=) is not missing."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    env_file = _make_file(
        tmp_path / ".env",
        content="HYACINE_GRAPH_TENANT_ID=common\nCLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-abcdefghijklmnop\n",
    )
    status, _label, detail = check_oauth_token(env_file)
    assert status == PASS
    assert str(env_file) in detail
    assert "EnvironmentFile" in detail


def test_oauth_token_env_file_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    env_file = _make_file(tmp_path / ".env", content="CLAUDE_CODE_OAUTH_TOKEN=sk-replace-me\n")
    status, _label, detail = check_oauth_token(env_file)
    assert status == FAIL
    assert "placeholder" in detail.lower()


def test_oauth_token_env_file_blank_value_is_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    """The wizard writes `CLAUDE_CODE_OAUTH_TOKEN=` when the token prompt is skipped."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    env_file = _make_file(tmp_path / ".env", content="CLAUDE_CODE_OAUTH_TOKEN=\n")
    status, _label, detail = check_oauth_token(env_file)
    assert status == FAIL
    assert "not set" in detail.lower()


def test_oauth_token_env_file_placeholder_not_hidden_by_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The systemd timer gets the .env value, so a good shell export can't mask it."""
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok-valid-token-value-12345")
    env_file = _make_file(
        tmp_path / ".env", content="CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat-replace-me\n"
    )
    status, _label, detail = check_oauth_token(env_file)
    assert status == FAIL
    assert "placeholder" in detail
    assert str(env_file) in detail
    assert "systemd timer" in detail


def test_oauth_token_shell_placeholder_names_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-replace-me")
    env_file = _make_file(
        tmp_path / ".env", content="CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-abcdefghijklmnop\n"
    )
    status, _label, detail = check_oauth_token(env_file)
    assert status == FAIL
    assert "placeholder" in detail
    assert "shell" in detail
    assert str(env_file) not in detail


def test_oauth_token_shell_and_env_file_differ_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-shellshellshellshell")
    env_file = _make_file(
        tmp_path / ".env", content="CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-filefilefilefilefile\n"
    )
    status, _label, detail = check_oauth_token(env_file)
    assert status == WARN
    assert "differ" in detail
    assert f"systemd timer uses {env_file}" in detail


def test_oauth_token_shell_and_env_file_same_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-abcdefghijklmnop")
    env_file = _make_file(
        tmp_path / ".env", content="CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-abcdefghijklmnop\n"
    )
    assert check_oauth_token(env_file) == (
        PASS, "CLAUDE_CODE_OAUTH_TOKEN is set and not a placeholder", ""
    )


def test_oauth_token_shell_only_warns_timer_lacks_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The user manager doesn't inherit shell rc exports, so the timer won't see it."""
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-abcdefghijklmnop")
    env_file = _make_file(tmp_path / ".env", content="HYACINE_GRAPH_TENANT_ID=common\n")
    status, _label, detail = check_oauth_token(env_file)
    assert status == WARN
    assert "only in the shell" in detail
    assert "claude login" in detail
    assert str(env_file) in detail


def test_oauth_token_falls_back_to_claude_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    """No token anywhere, but `claude login` credentials exist: usable, so WARN not FAIL."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    _make_file(isolated_home / ".claude" / ".credentials.json", content="{}")
    status, _label, detail = check_oauth_token(tmp_path / ".env")
    assert status == WARN
    assert "claude login" in detail


# ---------------------------------------------------------------------------
# check_llm_api_key
# ---------------------------------------------------------------------------

def _preset(pid: str) -> Provider:
    provider = by_id(pid)
    assert provider is not None
    return provider


@pytest.mark.parametrize("pid", ["deepseek-anthropic", "anthropic-console", "openai", "groq"])
def test_llm_api_key_missing_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pid: str
) -> None:
    monkeypatch.delenv("HYACINE_LLM_API_KEY", raising=False)
    env_file = _make_file(tmp_path / ".env", content="CLAUDE_CODE_OAUTH_TOKEN=\n")
    status, label, detail = check_llm_api_key(env_file, _preset(pid))
    assert status == FAIL
    assert pid in label
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in label
    assert f"HYACINE_LLM_API_KEY=... to {env_file}" in detail
    assert "401" in detail


def test_llm_api_key_read_from_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYACINE_LLM_API_KEY", raising=False)
    env_file = _make_file(
        tmp_path / ".env", content="HYACINE_LLM_API_KEY=sk-deepseek-0123456789abcdef\n"
    )
    status, _label, detail = check_llm_api_key(env_file, _preset("deepseek-anthropic"))
    assert status == PASS
    assert "EnvironmentFile" in detail


def test_llm_api_key_env_file_placeholder_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HYACINE_LLM_API_KEY", "sk-deepseek-0123456789abcdef")
    env_file = _make_file(tmp_path / ".env", content="HYACINE_LLM_API_KEY=replace-me\n")
    status, _label, detail = check_llm_api_key(env_file, _preset("deepseek-anthropic"))
    assert status == FAIL
    assert "placeholder" in detail
    assert str(env_file) in detail


def test_llm_api_key_shell_only_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYACINE_LLM_API_KEY", "sk-deepseek-0123456789abcdef")
    env_file = _make_file(tmp_path / ".env", content="HYACINE_GRAPH_TENANT_ID=common\n")
    status, _label, detail = check_llm_api_key(env_file, _preset("openai"))
    assert status == WARN
    assert "only in the shell" in detail
    assert "send no key" in detail


def test_llm_api_key_shell_and_env_file_differ_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HYACINE_LLM_API_KEY", "sk-shell-0123456789abcdef")
    env_file = _make_file(
        tmp_path / ".env", content="HYACINE_LLM_API_KEY=sk-file-0123456789abcdef\n"
    )
    status, _label, detail = check_llm_api_key(env_file, _preset("openai"))
    assert status == WARN
    assert "differ" in detail


def test_llm_api_key_optional_for_local_preset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HYACINE_LLM_API_KEY", raising=False)
    status, label, _detail = check_llm_api_key(tmp_path / ".env", _preset("ollama-local"))
    assert status == PASS
    assert "optional" in label


def test_llm_api_key_local_dummy_key_is_not_a_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Local servers ignore the key; guides suggest short dummies like this one."""
    monkeypatch.delenv("HYACINE_LLM_API_KEY", raising=False)
    env_file = _make_file(tmp_path / ".env", content="HYACINE_LLM_API_KEY=sk-no-key\n")
    status, _label, _detail = check_llm_api_key(env_file, _preset("ollama-local"))
    assert status == PASS


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("http://localhost:1234/v1", PASS),
        ("http://127.0.0.1:8000/v1", PASS),
        ("https://llm.example.com/v1", WARN),
    ],
)
def test_llm_api_key_custom_endpoint_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base_url: str, expected: str
) -> None:
    """A custom endpoint may not need a key, so a missing one never hard-fails."""
    monkeypatch.delenv("HYACINE_LLM_API_KEY", raising=False)
    provider = resolve(api_format="openai_chat", base_url=base_url)
    assert provider.category == "custom"
    status, _label, _detail = check_llm_api_key(tmp_path / ".env", provider)
    assert status == expected


# ---------------------------------------------------------------------------
# _non_cli_provider
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("recipient_email: a@b.com\n", ""),
        ("llm_provider: claude-code-oauth\n", ""),
        ("llm_provider: no-such-preset\n", ""),  # pipeline falls back to the CLI default
        ("llm_provider: deepseek-anthropic\n", "deepseek-anthropic"),
        ("llm_provider: openai\n", "openai"),
        ("llm_api_format: openai_chat\nllm_base_url: http://localhost:1234/v1\n", "custom"),
        ("run_time: 10:30\n", ""),  # unloadable config: check_config_yaml reports it
    ],
)
def test_non_cli_provider(tmp_path: Path, content: str, expected: str) -> None:
    f = _make_file(tmp_path / "config.yaml", content=content)
    provider = _non_cli_provider(f)
    assert (provider.id if provider is not None else "") == expected


def test_non_cli_provider_missing_config(tmp_path: Path) -> None:
    assert _non_cli_provider(tmp_path / "config.yaml") is None


# ---------------------------------------------------------------------------
# check_conflicting_keys
# ---------------------------------------------------------------------------

def test_no_conflicting_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    status, _label, _detail = check_conflicting_keys()
    assert status == PASS


def test_api_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-123")
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    status, _label, detail = check_conflicting_keys()
    assert status == WARN
    assert "ANTHROPIC_API_KEY" in detail


def test_auth_token_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-123")
    status, _label, detail = check_conflicting_keys()
    assert status == WARN
    assert "ANTHROPIC_AUTH_TOKEN" in detail


# ---------------------------------------------------------------------------
# check_config_yaml
# ---------------------------------------------------------------------------

def test_config_yaml_missing(tmp_path: Path) -> None:
    status, _label, _detail = check_config_yaml(tmp_path / "config.yaml")
    assert status == FAIL


def test_config_yaml_invalid(tmp_path: Path) -> None:
    f = _make_file(tmp_path / "config.yaml", content=": bad: yaml: [[\n")
    status, _label, detail = check_config_yaml(f)
    assert status == FAIL
    assert "parse" in detail.lower()


def test_config_yaml_valid(tmp_path: Path) -> None:
    f = _make_file(tmp_path / "config.yaml", content="recipient_email: a@b.com\n")
    status, _label, _detail = check_config_yaml(f)
    assert status == PASS


def test_config_yaml_example_is_valid() -> None:
    status, _label, detail = check_config_yaml(
        _REPO_ROOT / "examples" / "alice" / "config" / "config.yaml"
    )
    assert status == PASS, detail


def test_config_yaml_unquoted_run_time_fails(tmp_path: Path) -> None:
    """YAML 1.1 reads `10:30` as the integer 630, which YamlConfig rejects."""
    f = _make_file(
        tmp_path / "config.yaml",
        content="recipient_email: a@b.com\nrun_time: 10:30\n",
    )
    status, _label, detail = check_config_yaml(f)
    assert status == FAIL
    assert "run_time" in detail
    assert 'run_time: "10:30"' in detail


def test_config_yaml_quoted_run_time_passes(tmp_path: Path) -> None:
    f = _make_file(
        tmp_path / "config.yaml",
        content='recipient_email: a@b.com\nrun_time: "10:30"\n',
    )
    status, _label, detail = check_config_yaml(f)
    assert status == PASS, detail


def test_config_yaml_wrong_type_fails(tmp_path: Path) -> None:
    f = _make_file(
        tmp_path / "config.yaml",
        content="recipient_email: a@b.com\nllm_timeout_seconds: soon\n",
    )
    status, _label, detail = check_config_yaml(f)
    assert status == FAIL
    assert "llm_timeout_seconds" in detail
    assert "\n" not in detail


def test_config_yaml_not_a_mapping_fails(tmp_path: Path) -> None:
    f = _make_file(tmp_path / "config.yaml", content="- recipient_email: a@b.com\n")
    status, _label, detail = check_config_yaml(f)
    assert status == FAIL
    assert "schema" in detail.lower()


@pytest.mark.parametrize(
    "content",
    ["timezone: UTC\n", 'recipient_email: ""\n', "recipient_email: '   '\n"],
)
def test_config_yaml_empty_recipient_fails(tmp_path: Path, content: str) -> None:
    """run_pipeline raises on every run when recipient_email is empty."""
    f = _make_file(tmp_path / "config.yaml", content=content)
    status, _label, detail = check_config_yaml(f)
    assert status == FAIL
    assert "recipient_email" in detail


@pytest.mark.parametrize("tz", ["Mars/Base", "../etc/passwd", "UTC "])
def test_config_yaml_invalid_timezone_fails(tmp_path: Path, tz: str) -> None:
    f = _make_file(
        tmp_path / "config.yaml",
        content=f"recipient_email: a@b.com\ntimezone: '{tz}'\n",
    )
    status, _label, detail = check_config_yaml(f)
    assert status == FAIL
    assert "timezone" in detail


# ---------------------------------------------------------------------------
# check_rules_yaml
# ---------------------------------------------------------------------------

def test_rules_yaml_missing(tmp_path: Path) -> None:
    status, _label, _detail = check_rules_yaml(tmp_path / "rules.yaml")
    assert status == FAIL


def test_rules_yaml_valid(tmp_path: Path) -> None:
    f = _make_file(tmp_path / "rules.yaml", content="rules: []\n")
    status, _label, _detail = check_rules_yaml(f)
    assert status == PASS


def test_rules_yaml_starter_is_valid() -> None:
    """`hyacine init` copies the starter, so a fresh install must come up green."""
    status, _label, detail = check_rules_yaml(_REPO_ROOT / "config" / "rules.starter.yaml")
    assert status == PASS, detail


def test_rules_yaml_invalid_yaml(tmp_path: Path) -> None:
    f = _make_file(tmp_path / "rules.yaml", content="rules: [\n")
    status, _label, detail = check_rules_yaml(f)
    assert status == FAIL
    assert "parse" in detail.lower()


def test_rules_yaml_unknown_category_fails(tmp_path: Path) -> None:
    """load_rules rejects it, and the pipeline then classifies with no rules at all."""
    f = _make_file(
        tmp_path / "rules.yaml",
        content="rules:\n  - name: x\n    sender_domain: example.com\n    category: not-a-category\n",
    )
    status, _label, detail = check_rules_yaml(f)
    assert status == FAIL
    assert "rules.0.category" in detail
    assert "ignore every rule" in detail
    assert "\n" not in detail


def test_rules_yaml_bad_regex_fails(tmp_path: Path) -> None:
    f = _make_file(
        tmp_path / "rules.yaml",
        content="rules:\n  - name: x\n    subject_regex: '(unclosed'\n    category: other\n",
    )
    status, _label, detail = check_rules_yaml(f)
    assert status == FAIL
    assert "subject_regex" in detail


def test_rules_yaml_not_a_mapping_fails(tmp_path: Path) -> None:
    f = _make_file(tmp_path / "rules.yaml", content="- name: x\n  category: other\n")
    status, _label, detail = check_rules_yaml(f)
    assert status == FAIL
    assert "schema" in detail.lower()


# ---------------------------------------------------------------------------
# check_prompt_md
# ---------------------------------------------------------------------------

def test_prompt_md_missing(tmp_path: Path) -> None:
    status, _label, _detail = check_prompt_md(tmp_path / "prompts" / "hyacine.md")
    assert status == FAIL


def test_prompt_md_empty(tmp_path: Path) -> None:
    f = _make_file(tmp_path / "hyacine.md", content="")
    status, _label, detail = check_prompt_md(f)
    assert status == FAIL
    assert "empty" in detail.lower()


def test_prompt_md_unrendered_jinja(tmp_path: Path) -> None:
    f = _make_file(tmp_path / "hyacine.md", content="{{ name }} is the operator")
    status, _label, detail = check_prompt_md(f)
    assert status == WARN
    assert "jinja" in detail.lower() or "placeholder" in detail.lower()


def test_prompt_md_valid(tmp_path: Path) -> None:
    f = _make_file(
        tmp_path / "hyacine.md",
        content="You are Alice's daily assistant.\n",
    )
    status, _label, _detail = check_prompt_md(f)
    assert status == PASS


# ---------------------------------------------------------------------------
# check_db
# ---------------------------------------------------------------------------

def test_db_missing_is_warn(tmp_path: Path) -> None:
    status, _label, detail = check_db(tmp_path / "hyacine.db")
    assert status == WARN
    assert "first run" in detail.lower() or "ok" in detail.lower()


def test_db_exists_is_pass(tmp_path: Path) -> None:
    f = _make_file(tmp_path / "hyacine.db", content="SQLite format")
    status, _label, _detail = check_db(f)
    assert status == PASS


# ---------------------------------------------------------------------------
# check_auth_record
# ---------------------------------------------------------------------------

def test_auth_record_missing(tmp_path: Path) -> None:
    status, _label, detail = check_auth_record(tmp_path / "auth" / "auth_record.json")
    assert status == WARN
    assert "bootstrap" in detail.lower() or "run" in detail.lower()


def test_auth_record_exists_correct_mode(tmp_path: Path) -> None:
    record = _make_file(tmp_path / "auth" / "auth_record.json", content="{}", mode=0o600)
    status, _label, _detail = check_auth_record(record)
    assert status == PASS


def test_auth_record_wrong_mode(tmp_path: Path) -> None:
    record = _make_file(tmp_path / "auth" / "auth_record.json", content="{}", mode=0o644)
    status, _label, detail = check_auth_record(record)
    assert status == WARN
    assert "644" in detail


# ---------------------------------------------------------------------------
# check_claude_cli
# ---------------------------------------------------------------------------

def test_claude_cli_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYACINE_CLAUDE_BIN", raising=False)
    with patch("shutil.which", return_value=None):
        status, _label, detail = check_claude_cli()
    assert status == FAIL
    assert "not found" in detail.lower()


def test_claude_cli_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYACINE_CLAUDE_BIN", raising=False)
    with patch("shutil.which", return_value="/usr/bin/claude"), patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "claude 1.0.0\n"
        mock_run.return_value.stderr = ""
        mock_run.return_value.returncode = 0
        status, _label, detail = check_claude_cli()
    assert status == PASS
    assert "1.0.0" in detail
    assert mock_run.call_args.args[0] == ["/usr/bin/claude", "--version"]


def test_claude_cli_searches_local_bin(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    """Same lookup as the pipeline: ~/.local/bin is searched even when not on PATH."""
    monkeypatch.delenv("HYACINE_CLAUDE_BIN", raising=False)
    monkeypatch.setenv("PATH", "/nonexistent")
    claude = _make_file(isolated_home / ".local" / "bin" / "claude", content="#!/bin/sh\n", mode=0o755)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "claude 2.0.0\n"
        mock_run.return_value.stderr = ""
        mock_run.return_value.returncode = 0
        status, _label, detail = check_claude_cli()
    assert status == PASS
    assert str(claude) in detail


def test_claude_cli_uses_bin_override_from_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HYACINE_CLAUDE_BIN", raising=False)
    claude = _make_file(tmp_path / "opt" / "claude", content="#!/bin/sh\n", mode=0o755)
    env_file = _make_file(tmp_path / ".env", content=f"HYACINE_CLAUDE_BIN={claude}\n")
    with patch("shutil.which", return_value=None), patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "claude 2.0.0\n"
        mock_run.return_value.stderr = ""
        mock_run.return_value.returncode = 0
        status, _label, detail = check_claude_cli(env_file)
    assert status == PASS
    assert mock_run.call_args.args[0] == [str(claude), "--version"]


def test_claude_cli_bad_bin_override_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HYACINE_CLAUDE_BIN", str(tmp_path / "missing-claude"))
    status, _label, detail = check_claude_cli()
    assert status == FAIL
    assert "HYACINE_CLAUDE_BIN" in detail


def _fake_version(mock_run: MagicMock) -> None:
    mock_run.return_value.stdout = "claude 2.0.0\n"
    mock_run.return_value.stderr = ""
    mock_run.return_value.returncode = 0


def test_claude_cli_env_file_bad_bin_not_hidden_by_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The timer resolves the .env override, so a good shell one can't mask it."""
    good = _make_file(tmp_path / "opt" / "claude", content="#!/bin/sh\n", mode=0o755)
    monkeypatch.setenv("HYACINE_CLAUDE_BIN", str(good))
    env_file = _make_file(tmp_path / ".env", content=f"HYACINE_CLAUDE_BIN={tmp_path / 'gone'}\n")
    status, _label, detail = check_claude_cli(env_file)
    assert status == FAIL
    assert "gone" in detail
    assert str(env_file) in detail
    assert "systemd timer" in detail


def test_claude_cli_shell_bad_bin_names_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = _make_file(tmp_path / "opt" / "claude", content="#!/bin/sh\n", mode=0o755)
    monkeypatch.setenv("HYACINE_CLAUDE_BIN", str(tmp_path / "gone"))
    env_file = _make_file(tmp_path / ".env", content=f"HYACINE_CLAUDE_BIN={good}\n")
    status, _label, detail = check_claude_cli(env_file)
    assert status == FAIL
    assert "gone" in detail
    assert "shell" in detail


def test_claude_cli_shell_and_env_file_bins_differ_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from_file = _make_file(tmp_path / "a" / "claude", content="#!/bin/sh\n", mode=0o755)
    from_shell = _make_file(tmp_path / "b" / "claude", content="#!/bin/sh\n", mode=0o755)
    monkeypatch.setenv("HYACINE_CLAUDE_BIN", str(from_shell))
    env_file = _make_file(tmp_path / ".env", content=f"HYACINE_CLAUDE_BIN={from_file}\n")
    with patch("subprocess.run") as mock_run:
        _fake_version(mock_run)
        status, _label, detail = check_claude_cli(env_file)
    assert status == WARN
    assert mock_run.call_args.args[0] == [str(from_file), "--version"]
    assert "differ" in detail
    assert str(from_shell) in detail


def test_claude_cli_shell_and_env_file_same_bin_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude = _make_file(tmp_path / "opt" / "claude", content="#!/bin/sh\n", mode=0o755)
    monkeypatch.setenv("HYACINE_CLAUDE_BIN", str(claude))
    env_file = _make_file(tmp_path / ".env", content=f"HYACINE_CLAUDE_BIN={claude}\n")
    with patch("subprocess.run") as mock_run:
        _fake_version(mock_run)
        status, _label, _detail = check_claude_cli(env_file)
    assert status == PASS


def test_claude_cli_shell_only_bin_warns_timer_lacks_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude = _make_file(tmp_path / "opt" / "claude", content="#!/bin/sh\n", mode=0o755)
    monkeypatch.setenv("HYACINE_CLAUDE_BIN", str(claude))
    env_file = _make_file(tmp_path / ".env", content="HYACINE_GRAPH_TENANT_ID=common\n")
    with patch("subprocess.run") as mock_run:
        _fake_version(mock_run)
        status, _label, detail = check_claude_cli(env_file)
    assert status == WARN
    assert mock_run.call_args.args[0] == [str(claude), "--version"]
    assert "only in the shell" in detail


def test_claude_cli_nonzero_version_exit_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYACINE_CLAUDE_BIN", raising=False)
    with patch("shutil.which", return_value="/usr/bin/claude"), patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "error: broken install\n"
        mock_run.return_value.returncode = 1
        status, _label, detail = check_claude_cli()
    assert status == WARN
    assert "broken install" in detail


def test_claude_cli_not_needed_for_non_cli_provider() -> None:
    with patch("shutil.which", return_value=None):
        status, label, detail = check_claude_cli(None, "openai")
    assert status == PASS
    assert "reachable" not in label
    assert "openai" in detail


# ---------------------------------------------------------------------------
# run_checks
# ---------------------------------------------------------------------------

def _make_repo(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    config: str,
    env: str = "",
) -> Path:
    """A repo where every check but the LLM credential one passes."""
    _make_file(root / ".env", content=env)
    _make_file(root / "config" / "config.yaml", content=f"recipient_email: a@b.com\n{config}")
    _make_file(root / "config" / "rules.yaml", content="rules: []\n")
    _make_file(root / "prompts" / "hyacine.md", content="You are Alice's assistant.\n")
    _make_file(root / "data" / "hyacine.db", content="SQLite format")
    _make_file(root / "data" / "auth" / "auth_record.json", content="{}")
    monkeypatch.setenv("HYACINE_REPO_ROOT", str(root))
    for key in (
        "CLAUDE_CODE_OAUTH_TOKEN",
        "HYACINE_LLM_API_KEY",
        "HYACINE_CLAUDE_BIN",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "HYACINE_AUTH_DIR",
        "HYACINE_AUTH_RECORD_PATH",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(doctor, "check_systemctl", lambda: (PASS, "systemctl", ""))
    return root


def test_run_checks_http_provider_without_key_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_repo(tmp_path / "repo", monkeypatch, config="llm_provider: deepseek-anthropic\n")
    assert run_checks() == 2
    out = capsys.readouterr().out
    assert "HYACINE_LLM_API_KEY is set for llm_provider 'deepseek-anthropic'" in out
    assert "CLAUDE_CODE_OAUTH_TOKEN is set" not in out


def test_run_checks_http_provider_with_env_file_key_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_repo(
        tmp_path / "repo",
        monkeypatch,
        config="llm_provider: deepseek-anthropic\n",
        env="HYACINE_LLM_API_KEY=sk-deepseek-0123456789abcdef\n",
    )
    assert run_checks() == 0, capsys.readouterr().out


def test_run_checks_local_provider_without_key_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_repo(tmp_path / "repo", monkeypatch, config="llm_provider: ollama-local\n")
    assert run_checks() == 0, capsys.readouterr().out


def test_run_checks_uses_auth_record_path_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """bootstrap_auth writes Settings.auth_record_path, so doctor must look there."""
    repo = _make_repo(tmp_path / "repo", monkeypatch, config="llm_provider: ollama-local\n")
    (repo / "data" / "auth" / "auth_record.json").unlink()
    record = _make_file(tmp_path / "srv" / "rec.json", content="{}")
    monkeypatch.setenv("HYACINE_AUTH_RECORD_PATH", str(record))
    assert run_checks() == 0
    assert f"Graph auth record exists at {record}" in capsys.readouterr().out
