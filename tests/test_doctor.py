"""Tests for scripts/doctor.py."""
from __future__ import annotations

# Import the check functions directly for unit testing
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
    check_config_dir,
    check_config_yaml,
    check_conflicting_keys,
    check_db,
    check_env_file,
    check_oauth_token,
    check_prompt_md,
    check_rules_yaml,
    check_state_dir,
    run_checks,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dir(path: Path, mode: int = 0o700) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(mode)
    return path


def _make_file(path: Path, content: str = "# content\n", mode: int = 0o600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)
    return path


# ---------------------------------------------------------------------------
# check_config_dir
# ---------------------------------------------------------------------------

def test_config_dir_missing(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent"
    status, label, detail = check_config_dir(missing)
    assert status == FAIL
    assert "missing" in detail.lower() or "directory" in detail.lower()


def test_config_dir_wrong_mode(tmp_path: Path) -> None:
    d = _make_dir(tmp_path / "cfg", mode=0o755)
    status, label, detail = check_config_dir(d)
    assert status == WARN
    assert "755" in detail


def test_config_dir_correct(tmp_path: Path) -> None:
    d = _make_dir(tmp_path / "cfg", mode=0o700)
    status, label, detail = check_config_dir(d)
    assert status == PASS


# ---------------------------------------------------------------------------
# check_env_file
# ---------------------------------------------------------------------------

def test_env_file_missing(tmp_path: Path) -> None:
    status, label, detail = check_env_file(tmp_path / "hyacine.env")
    assert status == FAIL


def test_env_file_wrong_mode(tmp_path: Path) -> None:
    f = _make_file(tmp_path / "hyacine.env", mode=0o644)
    status, label, detail = check_env_file(f)
    assert status == WARN
    assert "644" in detail


def test_env_file_correct(tmp_path: Path) -> None:
    f = _make_file(tmp_path / "hyacine.env", mode=0o600)
    status, label, detail = check_env_file(f)
    assert status == PASS


# ---------------------------------------------------------------------------
# check_oauth_token
# ---------------------------------------------------------------------------

def test_oauth_token_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    status, label, detail = check_oauth_token()
    assert status == FAIL
    assert "not set" in detail.lower()


def test_oauth_token_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-replace-me")
    status, label, detail = check_oauth_token()
    assert status == FAIL
    assert "placeholder" in detail.lower()


def test_oauth_token_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok-valid-token-value-12345")
    status, label, detail = check_oauth_token()
    assert status == PASS


# ---------------------------------------------------------------------------
# check_conflicting_keys
# ---------------------------------------------------------------------------

def test_no_conflicting_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    status, label, detail = check_conflicting_keys()
    assert status == PASS


def test_api_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-123")
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    status, label, detail = check_conflicting_keys()
    assert status == WARN
    assert "ANTHROPIC_API_KEY" in detail


def test_auth_token_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-123")
    status, label, detail = check_conflicting_keys()
    assert status == WARN
    assert "ANTHROPIC_AUTH_TOKEN" in detail


# ---------------------------------------------------------------------------
# check_config_yaml
# ---------------------------------------------------------------------------

def test_config_yaml_missing(tmp_path: Path) -> None:
    status, label, detail = check_config_yaml(tmp_path / "config.yaml")
    assert status == FAIL


def test_config_yaml_invalid(tmp_path: Path) -> None:
    f = _make_file(tmp_path / "config.yaml", content=": bad: yaml: [[\n")
    status, label, detail = check_config_yaml(f)
    assert status == FAIL
    assert "parse" in detail.lower()


def test_config_yaml_valid(tmp_path: Path) -> None:
    f = _make_file(tmp_path / "config.yaml", content="recipient_email: a@b.com\n")
    status, label, detail = check_config_yaml(f)
    assert status == PASS


# ---------------------------------------------------------------------------
# check_rules_yaml
# ---------------------------------------------------------------------------

def test_rules_yaml_missing(tmp_path: Path) -> None:
    status, label, detail = check_rules_yaml(tmp_path / "rules.yaml")
    assert status == FAIL


def test_rules_yaml_valid(tmp_path: Path) -> None:
    f = _make_file(tmp_path / "rules.yaml", content="rules: []\n")
    status, label, detail = check_rules_yaml(f)
    assert status == PASS


# ---------------------------------------------------------------------------
# check_prompt_md
# ---------------------------------------------------------------------------

def test_prompt_md_missing(tmp_path: Path) -> None:
    status, label, detail = check_prompt_md(
        tmp_path / "prompts" / "hyacine.md",
        tmp_path / "config.yaml",
    )
    assert status == FAIL


def test_prompt_md_empty(tmp_path: Path) -> None:
    f = _make_file(tmp_path / "hyacine.md", content="")
    status, label, detail = check_prompt_md(f, tmp_path / "config.yaml")
    assert status == FAIL
    assert "empty" in detail.lower()


def test_prompt_md_unrendered_jinja(tmp_path: Path) -> None:
    f = _make_file(tmp_path / "hyacine.md", content="{{ name }} is the operator")
    status, label, detail = check_prompt_md(f, tmp_path / "config.yaml")
    assert status == WARN
    assert "jinja" in detail.lower() or "placeholder" in detail.lower()


def test_prompt_md_valid(tmp_path: Path) -> None:
    f = _make_file(
        tmp_path / "hyacine.md",
        content="You are Alice's daily briefing assistant.\n",
    )
    status, label, detail = check_prompt_md(f, tmp_path / "config.yaml")
    assert status == PASS


# ---------------------------------------------------------------------------
# check_state_dir
# ---------------------------------------------------------------------------

def test_state_dir_missing(tmp_path: Path) -> None:
    status, label, detail = check_state_dir(tmp_path / "nonexistent")
    assert status == FAIL


def test_state_dir_correct(tmp_path: Path) -> None:
    d = _make_dir(tmp_path / "state", mode=0o700)
    status, label, detail = check_state_dir(d)
    assert status == PASS


# ---------------------------------------------------------------------------
# check_db
# ---------------------------------------------------------------------------

def test_db_missing_is_warn(tmp_path: Path) -> None:
    status, label, detail = check_db(tmp_path)
    assert status == WARN
    assert "first run" in detail.lower() or "ok" in detail.lower()


def test_db_exists_is_pass(tmp_path: Path) -> None:
    _make_file(tmp_path / "hyacine.db", content="SQLite format")
    status, label, detail = check_db(tmp_path)
    assert status == PASS


# ---------------------------------------------------------------------------
# check_auth_record
# ---------------------------------------------------------------------------

def test_auth_record_missing(tmp_path: Path) -> None:
    status, label, detail = check_auth_record(tmp_path)
    assert status == WARN
    assert "bootstrap" in detail.lower() or "run" in detail.lower()


def test_auth_record_exists_correct_mode(tmp_path: Path) -> None:
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir()
    _make_file(auth_dir / "auth_record.json", content="{}", mode=0o600)
    status, label, detail = check_auth_record(tmp_path)
    assert status == PASS


def test_auth_record_wrong_mode(tmp_path: Path) -> None:
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir()
    _make_file(auth_dir / "auth_record.json", content="{}", mode=0o644)
    status, label, detail = check_auth_record(tmp_path)
    assert status == WARN
    assert "644" in detail


# ---------------------------------------------------------------------------
# check_claude_cli
# ---------------------------------------------------------------------------

def test_claude_cli_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    with patch("shutil.which", return_value=None):
        status, label, detail = check_claude_cli()
    assert status == FAIL
    assert "not found" in detail.lower()


def test_claude_cli_found(monkeypatch: pytest.MonkeyPatch) -> None:
    with patch("shutil.which", return_value="/usr/bin/claude"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = "claude 1.0.0\n"
            mock_run.return_value.stderr = ""
            mock_run.return_value.returncode = 0
            status, label, detail = check_claude_cli()
    assert status == PASS
    assert "1.0.0" in detail


# ---------------------------------------------------------------------------
# run_checks — integration
# ---------------------------------------------------------------------------

def test_run_checks_all_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With missing dirs/files and no token, should return 2."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    config_dir = tmp_path / "missing_config"
    state_dir = tmp_path / "missing_state"

    with patch("shutil.which", return_value=None):
        rc = run_checks(config_dir=config_dir, state_dir=state_dir)

    assert rc == 2


def test_run_checks_warns_for_db_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """State dir present but no DB → should warn, not hard fail."""
    config_dir = tmp_path / "cfg"
    config_dir.mkdir(mode=0o700)
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)

    # Create required files
    _make_file(config_dir / "hyacine.env", content="CLAUDE_CODE_OAUTH_TOKEN=tok-valid\n")
    _make_file(
        config_dir / "config.yaml",
        content="recipient_email: a@b.com\n",
        mode=0o644,
    )
    _make_file(config_dir / "rules.yaml", content="rules: []\n", mode=0o644)
    _make_file(
        config_dir / "prompts" / "hyacine.md",
        content="You are Alice's briefing assistant.\n",
        mode=0o644,
    )

    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok-valid-and-long-enough")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    with patch("shutil.which", return_value="/usr/bin/claude"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = "claude 1.0.0\n"
            mock_run.return_value.stderr = ""
            mock_run.return_value.returncode = 0
            rc = run_checks(config_dir=config_dir, state_dir=state_dir)

    # DB missing → WARN → rc=1, not 2
    assert rc in (1, 0)  # 0 if systemctl also passes, 1 if any warn
