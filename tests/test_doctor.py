"""Tests for scripts/doctor.py."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from doctor import (  # noqa: E402
    FAIL,
    PASS,
    WARN,
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

def test_oauth_token_missing(monkeypatch: pytest.MonkeyPatch) -> None:
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When env_file is passed, the FAIL detail must mention that resolved path."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    env_file = tmp_path / "custom" / ".env"
    status, _label, detail = check_oauth_token(env_file)
    assert status == FAIL
    assert str(env_file) in detail


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

def test_claude_cli_not_found() -> None:
    with patch("shutil.which", return_value=None):
        status, _label, detail = check_claude_cli()
    assert status == FAIL
    assert "not found" in detail.lower()


def test_claude_cli_found() -> None:
    with patch("shutil.which", return_value="/usr/bin/claude"), patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "claude 1.0.0\n"
        mock_run.return_value.stderr = ""
        mock_run.return_value.returncode = 0
        status, _label, detail = check_claude_cli()
    assert status == PASS
    assert "1.0.0" in detail
