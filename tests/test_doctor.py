"""Tests for scripts/doctor.py."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

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
    check_oauth_token,
    check_prompt_md,
    check_rules_yaml,
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


def test_oauth_token_environment_wins_over_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok-valid-token-value-12345")
    env_file = _make_file(tmp_path / ".env", content="CLAUDE_CODE_OAUTH_TOKEN=sk-replace-me\n")
    status, _label, detail = check_oauth_token(env_file)
    assert status == PASS
    assert detail == ""


def test_oauth_token_falls_back_to_claude_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    """No token anywhere, but `claude login` credentials exist: usable, so WARN not FAIL."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    _make_file(isolated_home / ".claude" / ".credentials.json", content="{}")
    status, _label, detail = check_oauth_token(tmp_path / ".env")
    assert status == WARN
    assert "claude login" in detail


def test_oauth_token_not_needed_for_non_cli_provider(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    status, _label, detail = check_oauth_token(None, "deepseek-anthropic")
    assert status == PASS
    assert "deepseek-anthropic" in detail


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
    assert _non_cli_provider(f) == expected


def test_non_cli_provider_missing_config(tmp_path: Path) -> None:
    assert _non_cli_provider(tmp_path / "config.yaml") == ""


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
    status, _label, detail = check_auth_record(tmp_path / "auth")
    assert status == WARN
    assert "bootstrap" in detail.lower() or "run" in detail.lower()


def test_auth_record_exists_correct_mode(tmp_path: Path) -> None:
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir()
    _make_file(auth_dir / "auth_record.json", content="{}", mode=0o600)
    status, _label, _detail = check_auth_record(auth_dir)
    assert status == PASS


def test_auth_record_wrong_mode(tmp_path: Path) -> None:
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir()
    _make_file(auth_dir / "auth_record.json", content="{}", mode=0o644)
    status, _label, detail = check_auth_record(auth_dir)
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
        status, _label, detail = check_claude_cli(None, "openai")
    assert status == PASS
    assert "openai" in detail
