"""Tests for the briefing init wizard (src/hyacine/cli/init.py)."""
from __future__ import annotations

import builtins
import stat
import textwrap
from pathlib import Path

import pytest

from hyacine.cli.init import (
    _ask,
    _build_config_yaml,
    _build_env_file,
    _render_prompt,
    _validate_tz,
    run_init,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _answer_sequence(answers: list[str]):
    """Return a mock for builtins.input that replays *answers* in order."""
    it = iter(answers)

    def _input(_prompt: str = "") -> str:
        try:
            return next(it)
        except StopIteration:
            return ""

    return _input


def _minimal_answers() -> list[str]:
    """Minimal valid stdin sequence for run_init wizard."""
    return [
        "Alice",                    # name
        "PM at Acme Robotics",      # role
        "I focus on product.",      # identity blurb line 1
        "",                         # blank → end identity blurb
        "Direct reports",           # priority 1
        "",                         # blank → end priorities
        "a",                        # accept default categories
        "alice@example.com",        # email recipient
        "UTC",                      # timezone
        "en",                       # language
        "07:30",                    # run time
        "common",                   # tenant id
        "",                         # ntfy topic
        "",                         # healthchecks uuid
    ]


# ---------------------------------------------------------------------------
# Unit: _validate_tz
# ---------------------------------------------------------------------------

def test_validate_tz_valid() -> None:
    _validate_tz("UTC")
    _validate_tz("America/New_York")
    _validate_tz("Europe/London")


def test_validate_tz_invalid() -> None:
    with pytest.raises(ValueError, match="not a valid IANA"):
        _validate_tz("NotATimezone")


def test_validate_tz_empty() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        _validate_tz("")


# ---------------------------------------------------------------------------
# Unit: _build_config_yaml
# ---------------------------------------------------------------------------

def test_build_config_yaml_keys() -> None:
    import yaml

    answers: dict[str, object] = {
        "email_recipient": "alice@example.com",
        "timezone": "UTC",
        "run_time": "07:30",
        "language": "en",
    }
    content = _build_config_yaml(answers)
    data = yaml.safe_load(content)
    assert data["recipient_email"] == "alice@example.com"
    assert data["timezone"] == "UTC"
    assert data["language"] == "en"
    assert "llm_model" in data


# ---------------------------------------------------------------------------
# Unit: _build_env_file
# ---------------------------------------------------------------------------

def test_build_env_file() -> None:
    answers: dict[str, object] = {
        "oauth_token": "tok-123",
        "graph_tenant_id": "common",
        "ntfy_topic": "my-topic",
        "healthchecks_uuid": "abc-123",
    }
    content = _build_env_file(answers)
    assert "CLAUDE_CODE_OAUTH_TOKEN=tok-123" in content
    assert "HYACINE_GRAPH_TENANT_ID=common" in content
    assert "HYACINE_NTFY_TOPIC=my-topic" in content
    assert "HYACINE_HEALTHCHECKS_UUID=abc-123" in content


def test_build_env_file_no_token() -> None:
    answers: dict[str, object] = {
        "oauth_token": "",
        "graph_tenant_id": "common",
        "ntfy_topic": "",
        "healthchecks_uuid": "",
    }
    content = _build_env_file(answers)
    assert "CLAUDE_CODE_OAUTH_TOKEN=" in content


# ---------------------------------------------------------------------------
# Unit: _render_prompt
# ---------------------------------------------------------------------------

def test_render_prompt_substitution(tmp_path: Path) -> None:
    """Template placeholders are replaced with wizard answers."""
    # Write a minimal template
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    template = prompts_dir / "hyacine.md.template"
    template.write_text(
        textwrap.dedent("""\
            {%- if language == "zh-CN" -%}
            ZH: {{ name }}
            {%- else -%}
            EN: {{ name }} ({{ role }})
            {% for p in priorities %}- {{ p }}
            {% endfor %}
            recipient: {{ email_recipient }}
            tz: {{ timezone_display }}
            {%- endif %}
        """),
        encoding="utf-8",
    )

    # Patch _repo_root so it points at our tmp_path
    answers: dict[str, object] = {
        "name": "Alice",
        "role": "PM at Acme",
        "identity_blurb": "Focus on product.",
        "priorities": ["direct reports", "deadlines"],
        "categories_md": "- cat1\n- cat2",
        "email_recipient": "alice@example.com",
        "timezone": "UTC",
        "language": "en",
    }

    rendered = _render_prompt(answers, tmp_path)
    assert "Alice" in rendered
    assert "PM at Acme" in rendered
    assert "direct reports" in rendered
    assert "alice@example.com" in rendered
    assert "UTC" in rendered


def test_render_prompt_zh(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    template = prompts_dir / "hyacine.md.template"
    template.write_text(
        "{% if language == 'zh-CN' %}ZH:{{ name }}{% else %}EN:{{ name }}{% endif %}",
        encoding="utf-8",
    )
    answers: dict[str, object] = {
        "name": "小明",
        "role": "工程师",
        "identity_blurb": "研究方向",
        "priorities": ["紧急任务"],
        "categories_md": "- 分类",
        "email_recipient": "xm@example.com",
        "timezone": "UTC",
        "language": "zh-CN",
    }
    rendered = _render_prompt(answers, tmp_path)
    assert "ZH:小明" in rendered


# ---------------------------------------------------------------------------
# Integration: fresh run writes all expected files with correct chmod
# ---------------------------------------------------------------------------

def test_fresh_run_writes_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "config"

    # Set up environment so XDG dirs are in tmp_path
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg_config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg_state"))

    # Create a minimal template
    repo_root = tmp_path / "repo"
    prompts_dir = repo_root / "prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "hyacine.md.template").write_text(
        "{{ name }} ({{ role }}) — {{ email_recipient }}",
        encoding="utf-8",
    )
    (repo_root / "config").mkdir()
    (repo_root / "config" / "rules.starter.yaml").write_text("rules: []\n", encoding="utf-8")

    # Patch _repo_root and getpass
    import hyacine.cli.init as init_mod  # noqa: PLC0415

    monkeypatch.setattr(init_mod, "_repo_root", lambda: repo_root)

    # Provide token via getpass mock
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": "tok-valid-token")

    answers = _minimal_answers()
    monkeypatch.setattr(builtins, "input", _answer_sequence(answers))

    rc = run_init(["--config-dir", str(config_dir)])
    assert rc == 0

    assert (config_dir / "config.yaml").exists()
    assert (config_dir / "rules.yaml").exists()
    assert (config_dir / "prompts" / "hyacine.md").exists()
    env_file = config_dir / "hyacine.env"
    assert env_file.exists()

    # hyacine.env must be chmod 600
    mode = stat.S_IMODE(env_file.stat().st_mode)
    assert oct(mode)[-3:] == "600", f"Expected 600, got {oct(mode)[-3:]}"

    # Rendered prompt should contain the name
    rendered = (config_dir / "prompts" / "hyacine.md").read_text(encoding="utf-8")
    assert "Alice" in rendered


# ---------------------------------------------------------------------------
# Integration: --no-prompt-token skips OAuth token prompt
# ---------------------------------------------------------------------------

def test_no_prompt_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "config"

    repo_root = tmp_path / "repo"
    (repo_root / "prompts").mkdir(parents=True)
    (repo_root / "prompts" / "hyacine.md.template").write_text(
        "{{ name }}", encoding="utf-8"
    )
    (repo_root / "config").mkdir()
    (repo_root / "config" / "rules.starter.yaml").write_text("rules: []\n", encoding="utf-8")

    import hyacine.cli.init as init_mod  # noqa: PLC0415

    monkeypatch.setattr(init_mod, "_repo_root", lambda: repo_root)

    # getpass should NOT be called
    called = []

    def _no_getpass(_prompt: str = "") -> str:
        called.append(True)
        return "should-not-be-called"

    monkeypatch.setattr("getpass.getpass", _no_getpass)

    answers = _minimal_answers()
    monkeypatch.setattr(builtins, "input", _answer_sequence(answers))

    rc = run_init(["--config-dir", str(config_dir), "--no-prompt-token"])
    assert rc == 0
    assert not called, "getpass should not have been called with --no-prompt-token"

    env_content = (config_dir / "hyacine.env").read_text(encoding="utf-8")
    assert "CLAUDE_CODE_OAUTH_TOKEN=" in env_content


# ---------------------------------------------------------------------------
# Integration: --overwrite backs up existing files and replaces
# ---------------------------------------------------------------------------

def test_overwrite_backs_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)

    # Pre-create a config.yaml
    existing = config_dir / "config.yaml"
    existing.write_text("recipient_email: old@example.com\n", encoding="utf-8")

    repo_root = tmp_path / "repo"
    (repo_root / "prompts").mkdir(parents=True)
    (repo_root / "prompts" / "hyacine.md.template").write_text(
        "{{ name }}", encoding="utf-8"
    )
    (repo_root / "config").mkdir()
    (repo_root / "config" / "rules.starter.yaml").write_text("rules: []\n", encoding="utf-8")

    import hyacine.cli.init as init_mod  # noqa: PLC0415

    monkeypatch.setattr(init_mod, "_repo_root", lambda: repo_root)
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": "tok-new")

    answers = _minimal_answers()
    monkeypatch.setattr(builtins, "input", _answer_sequence(answers))

    rc = run_init(["--config-dir", str(config_dir), "--overwrite"])
    assert rc == 0

    # A backup file should exist
    bak_files = list(config_dir.glob("config.yaml.bak-*"))
    assert bak_files, "Expected a backup file for config.yaml"
    bak_content = bak_files[0].read_text(encoding="utf-8")
    assert "old@example.com" in bak_content

    # New config should have the wizard's answer
    new_content = existing.read_text(encoding="utf-8")
    assert "alice@example.com" in new_content


# ---------------------------------------------------------------------------
# Integration: skip all when user chooses [s]
# ---------------------------------------------------------------------------

def test_skip_all_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    config_dir.chmod(0o700)

    # Pre-create all target files
    for name in ["hyacine.env", "config.yaml", "rules.yaml"]:
        (config_dir / name).write_text("# existing\n", encoding="utf-8")
    (config_dir / "prompts").mkdir(exist_ok=True)
    (config_dir / "prompts" / "hyacine.md").write_text("# existing prompt\n", encoding="utf-8")

    repo_root = tmp_path / "repo"
    (repo_root / "prompts").mkdir(parents=True)
    (repo_root / "prompts" / "hyacine.md.template").write_text("{{ name }}", encoding="utf-8")
    (repo_root / "config").mkdir()
    (repo_root / "config" / "rules.starter.yaml").write_text("rules: []\n", encoding="utf-8")

    import hyacine.cli.init as init_mod  # noqa: PLC0415

    monkeypatch.setattr(init_mod, "_repo_root", lambda: repo_root)

    # User picks 's' at first prompt → skip all
    monkeypatch.setattr(builtins, "input", _answer_sequence(["s"]))

    rc = run_init(["--config-dir", str(config_dir)])
    assert rc == 0

    # Existing files should be unchanged
    assert (config_dir / "config.yaml").read_text() == "# existing\n"


# ---------------------------------------------------------------------------
# Integration: ZoneInfo validation rejects garbage tz names
# ---------------------------------------------------------------------------

def test_bad_timezone_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "config"

    repo_root = tmp_path / "repo"
    (repo_root / "prompts").mkdir(parents=True)
    (repo_root / "prompts" / "hyacine.md.template").write_text("{{ name }}", encoding="utf-8")
    (repo_root / "config").mkdir()
    (repo_root / "config" / "rules.starter.yaml").write_text("rules: []\n", encoding="utf-8")

    import hyacine.cli.init as init_mod  # noqa: PLC0415

    monkeypatch.setattr(init_mod, "_repo_root", lambda: repo_root)
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": "tok-abc")

    # First timezone answer is garbage, second is valid
    answers_with_bad_tz = [
        "Alice",
        "PM at Acme",
        "Focus on product.",
        "",
        "Direct reports",
        "",
        "a",
        "alice@example.com",
        "NotATimezone",   # invalid tz — wizard should re-prompt
        "UTC",            # valid tz
        "en",
        "07:30",
        "common",
        "",
        "",
    ]
    monkeypatch.setattr(builtins, "input", _answer_sequence(answers_with_bad_tz))

    rc = run_init(["--config-dir", str(config_dir)])
    assert rc == 0

    config_content = (config_dir / "config.yaml").read_text(encoding="utf-8")
    assert "UTC" in config_content


# ---------------------------------------------------------------------------
# Unit: _ask helper
# ---------------------------------------------------------------------------

def test_ask_with_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builtins, "input", lambda _p="": "")
    result = _ask("Prompt", default="mydefault")
    assert result == "mydefault"


def test_ask_with_user_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builtins, "input", lambda _p="": "  user value  ")
    result = _ask("Prompt", default="default")
    assert result == "user value"
