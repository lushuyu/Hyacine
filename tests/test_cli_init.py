"""Tests for the hyacine init wizard (src/hyacine/cli/init.py)."""
from __future__ import annotations

import builtins
import stat
import textwrap
from pathlib import Path

import pytest
import yaml

from hyacine.cli.init import (
    _ask,
    _build_config_yaml,
    _build_env_file,
    _current_value,
    _parse_env_file,
    _render_prompt,
    _validate_time,
    _validate_tz,
    run_init,
)
from hyacine.config import YamlConfig, load_yaml_config
from hyacine.llm.providers import DEFAULT_CLAUDE_MODEL


def _answer_sequence(answers: list[str]):
    it = iter(answers)

    def _input(_prompt: str = "") -> str:
        try:
            return next(it)
        except StopIteration:
            return ""

    return _input


def _minimal_answers() -> list[str]:
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


def _setup_repo(repo_root: Path) -> None:
    """Create the minimum repo skeleton the wizard expects."""
    (repo_root / "prompts").mkdir(parents=True, exist_ok=True)
    (repo_root / "prompts" / "hyacine.md.template").write_text(
        "{{ name }} ({{ role }}) — {{ email_recipient }}",
        encoding="utf-8",
    )
    (repo_root / "config").mkdir(exist_ok=True)
    (repo_root / "config" / "rules.starter.yaml").write_text(
        "rules: []\n", encoding="utf-8"
    )


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
    assert data["llm_model"] == DEFAULT_CLAUDE_MODEL


def _config_answers() -> dict[str, object]:
    return {
        "email_recipient": "alice@example.com",
        "timezone": "UTC",
        "run_time": "07:30",
        "language": "en",
    }


def test_build_config_yaml_non_wizard_fields_follow_yamlconfig() -> None:
    """Fields the wizard doesn't ask about must track YamlConfig's defaults
    (they used to be hard-coded here and drifted: llm_model stayed "sonnet")."""
    import yaml

    data = yaml.safe_load(_build_config_yaml(_config_answers()))
    defaults = YamlConfig.model_construct()
    for name in (
        "llm_model",
        "llm_timeout_seconds",
        "fetch_max_emails",
        "initial_watermark_lookback_hours",
    ):
        assert data[name] == getattr(defaults, name), name


def test_build_config_yaml_ignores_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """YamlConfig is a BaseSettings, so a bare YamlConfig() would read these
    from the shell and bake them into the generated config.yaml."""
    import yaml

    monkeypatch.setenv("LLM_MODEL", "leaked-model")
    monkeypatch.setenv("FETCH_MAX_EMAILS", "7")
    data = yaml.safe_load(_build_config_yaml(_config_answers()))
    assert data["llm_model"] == DEFAULT_CLAUDE_MODEL
    assert data["fetch_max_emails"] == YamlConfig.model_fields["fetch_max_emails"].default


def test_build_config_yaml_update_keeps_unasked_keys() -> None:
    existing: dict[str, object] = {
        "recipient_email": "old@example.com",
        "timezone": "Asia/Singapore",
        "run_time": "07:30",
        "language": "zh-CN",
        "llm_model": "claude-opus-4-7",
        "llm_timeout_seconds": 600,
        "llm_provider": "deepseek-anthropic",
        "llm_base_url": "https://api.deepseek.com/anthropic",
        "llm_api_format": "anthropic_http",
        "identity": {"name": "Alice"},
        "fetch_max_emails": None,  # null → falls back to the declared default
    }
    data = yaml.safe_load(_build_config_yaml(_config_answers(), existing=existing))
    # The four answered keys are replaced...
    assert data["recipient_email"] == "alice@example.com"
    assert data["timezone"] == "UTC"
    assert data["language"] == "en"
    # ...everything else survives.
    assert data["llm_model"] == "claude-opus-4-7"
    assert data["llm_timeout_seconds"] == 600
    assert data["llm_provider"] == "deepseek-anthropic"
    assert data["llm_base_url"] == "https://api.deepseek.com/anthropic"
    assert data["llm_api_format"] == "anthropic_http"
    assert data["identity"] == {"name": "Alice"}
    assert data["fetch_max_emails"] == YamlConfig.model_fields["fetch_max_emails"].default
    assert existing["recipient_email"] == "old@example.com", "caller's dict must not be mutated"


def test_current_value_drops_unusable_defaults() -> None:
    current: dict[str, object] = {
        "timezone": "Mars/Base",
        "run_time": 630,  # unquoted 10:30 in YAML 1.1
        "language": "zh-CN",
        "recipient_email": "  ",
    }
    assert _current_value(current, "timezone", _validate_tz) is None
    assert _current_value(current, "run_time", _validate_time) is None
    assert _current_value(current, "language") == "zh-CN"
    assert _current_value(current, "recipient_email") is None
    assert _current_value(None, "language") is None


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


def test_build_env_file_merge_preserves_existing_and_unknown_keys() -> None:
    existing = {
        "CLAUDE_CODE_OAUTH_TOKEN": "old-secret-token",
        "HYACINE_GRAPH_TENANT_ID": "old-tenant",
        "HYACINE_NTFY_TOPIC": "old-topic",
        "HYACINE_HEALTHCHECKS_UUID": "old-uuid",
        "USER_CUSTOM_KEY": "user-value",
        "ANOTHER_UNRELATED": "please-keep-me",
    }
    answers: dict[str, object] = {
        "oauth_token": "",                   # blank → keep old token
        "graph_tenant_id": "new-tenant",     # provided → override
        "ntfy_topic": "",                    # blank → keep old topic
        "healthchecks_uuid": "new-uuid",     # provided → override
    }
    content = _build_env_file(answers, existing=existing)
    assert "CLAUDE_CODE_OAUTH_TOKEN=old-secret-token" in content
    assert "HYACINE_GRAPH_TENANT_ID=new-tenant" in content
    assert "HYACINE_NTFY_TOPIC=old-topic" in content
    assert "HYACINE_HEALTHCHECKS_UUID=new-uuid" in content
    assert "USER_CUSTOM_KEY=user-value" in content
    assert "ANOTHER_UNRELATED=please-keep-me" in content


def test_parse_env_file_round_trip(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment line\n\nFOO=bar\nBAZ=qux=with=equals\n# trailing comment\n",
        encoding="utf-8",
    )
    parsed = _parse_env_file(env_file)
    assert parsed == {"FOO": "bar", "BAZ": "qux=with=equals"}


def test_parse_env_file_handles_dotenv_grammar(tmp_path: Path) -> None:
    """Covers export prefix, quoting, and inline-comment edge cases."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join([
            "export EXPORTED=yes",
            'QUOTED_DOUBLE="value with spaces"',
            "QUOTED_SINGLE='raw $value'",
            "WITH_INLINE=clean # trailing comment",
            "HASH_IN_QUOTES=\"foo#bar\"",
            "",
        ]),
        encoding="utf-8",
    )
    parsed = _parse_env_file(env_file)
    assert parsed["EXPORTED"] == "yes"
    assert parsed["QUOTED_DOUBLE"] == "value with spaces"
    assert parsed["QUOTED_SINGLE"] == "raw $value"
    assert parsed["WITH_INLINE"] == "clean"
    assert parsed["HASH_IN_QUOTES"] == "foo#bar"


def test_parse_env_file_missing_returns_empty(tmp_path: Path) -> None:
    assert _parse_env_file(tmp_path / "does-not-exist.env") == {}


def test_update_resolution_preserves_existing_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    _setup_repo(repo_root)

    env_file = repo_root / ".env"
    env_file.write_text(
        "CLAUDE_CODE_OAUTH_TOKEN=preserved-token\n"
        "HYACINE_GRAPH_TENANT_ID=preserved-tenant\n"
        "USER_CUSTOM_KEY=keep-this-too\n",
        encoding="utf-8",
    )

    answers_blank_secrets = [
        "Alice", "PM at Acme", "Focus.", "",
        "Direct reports", "",
        "a",
        "alice@example.com", "UTC", "en", "07:30",
        "",                             # tenant → keeps preserved-tenant
        "", "",
    ]

    monkeypatch.setattr("getpass.getpass", lambda _prompt="": "")
    # Only .env exists, so 'u' answers the one file prompt.
    prompts: list[str] = []
    replies = _answer_sequence(["u"] + answers_blank_secrets)

    def _input(prompt: str = "") -> str:
        prompts.append(prompt)
        return replies(prompt)

    monkeypatch.setattr(builtins, "input", _input)

    rc = run_init(["--repo-root", str(repo_root)])
    assert rc == 0

    content = env_file.read_text(encoding="utf-8")
    assert "CLAUDE_CODE_OAUTH_TOKEN=preserved-token" in content
    assert "HYACINE_GRAPH_TENANT_ID=preserved-tenant" in content
    assert "USER_CUSTOM_KEY=keep-this-too" in content
    assert "Microsoft tenant ID (UUID or 'common') [preserved-tenant]: " in prompts


def test_update_typed_tenant_overrides_existing_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    _setup_repo(repo_root)
    env_file = repo_root / ".env"
    env_file.write_text("HYACINE_GRAPH_TENANT_ID=preserved-tenant\n", encoding="utf-8")

    monkeypatch.setattr("getpass.getpass", lambda _prompt="": "")
    monkeypatch.setattr(builtins, "input", _answer_sequence(["u"] + _minimal_answers()))

    rc = run_init(["--repo-root", str(repo_root)])
    assert rc == 0
    content = env_file.read_text(encoding="utf-8")
    assert "HYACINE_GRAPH_TENANT_ID=common" in content
    assert "preserved-tenant" not in content


@pytest.mark.parametrize("resolution", ["b", None])
def test_tenant_defaults_to_common_without_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resolution: str | None
) -> None:
    """Fresh installs and backup-and-overwrite start from 'common', not the old .env."""
    repo_root = tmp_path / "repo"
    _setup_repo(repo_root)
    env_file = repo_root / ".env"
    if resolution is not None:
        env_file.write_text("HYACINE_GRAPH_TENANT_ID=old-tenant\n", encoding="utf-8")
    answers = _minimal_answers()
    answers[answers.index("common")] = ""
    if resolution is not None:
        answers.insert(0, resolution)

    monkeypatch.setattr("getpass.getpass", lambda _prompt="": "")
    monkeypatch.setattr(builtins, "input", _answer_sequence(answers))

    rc = run_init(["--repo-root", str(repo_root)])
    assert rc == 0
    assert "HYACINE_GRAPH_TENANT_ID=common" in env_file.read_text(encoding="utf-8")


_EXISTING_CONFIG = """\
recipient_email: old@example.com
timezone: Asia/Singapore
language: zh-CN
run_time: '07:30'
llm_model: claude-opus-4-7
llm_timeout_seconds: 600
llm_provider: deepseek-anthropic
llm_base_url: https://api.deepseek.com/anthropic
llm_api_format: anthropic_http
identity:
  name: Alice
"""
_CUSTOM_RULES = (
    "rules:\n  - name: boss\n    sender_email: boss@example.com\n    category: priority\n"
)
_CUSTOM_PROMPT = "Hand-tuned zh-CN prompt.\n"


def _setup_existing_install(repo_root: Path) -> dict[str, Path]:
    _setup_repo(repo_root)
    files = {
        "env": repo_root / ".env",
        "config": repo_root / "config" / "config.yaml",
        "rules": repo_root / "config" / "rules.yaml",
        "prompt": repo_root / "prompts" / "hyacine.md",
    }
    files["env"].write_text(
        "CLAUDE_CODE_OAUTH_TOKEN=preserved-token\nUSER_CUSTOM_KEY=keep\n", encoding="utf-8"
    )
    files["env"].chmod(0o644)
    files["config"].write_text(_EXISTING_CONFIG, encoding="utf-8")
    files["rules"].write_text(_CUSTOM_RULES, encoding="utf-8")
    files["prompt"].write_text(_CUSTOM_PROMPT, encoding="utf-8")
    return files


def _backups(path: Path) -> list[Path]:
    return sorted(path.parent.glob(f"{path.name}.bak-*"))


def test_update_all_files_backs_up_and_keeps_unasked_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """'u' for every file must not silently reset llm_* / rules / the prompt."""
    repo_root = tmp_path / "repo"
    files = _setup_existing_install(repo_root)

    answers = [
        "u", "u", "u", "u",            # .env, config.yaml, rules.yaml, hyacine.md
        "Alice", "PM at Acme", "Focus.", "",
        "Direct reports", "",
        "a",
        "new@example.com",             # recipient → replaced
        "",                            # timezone → keeps Asia/Singapore
        "",                            # language → keeps zh-CN
        "10:30",                       # run_time → replaced
        "common",
        "", "",
    ]
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": "")
    monkeypatch.setattr(builtins, "input", _answer_sequence(answers))

    rc = run_init(["--repo-root", str(repo_root)])
    assert rc == 0

    # config.yaml: answered keys updated, everything else kept, still loads.
    data = yaml.safe_load(files["config"].read_text(encoding="utf-8"))
    assert data["recipient_email"] == "new@example.com"
    assert data["timezone"] == "Asia/Singapore"
    assert data["language"] == "zh-CN"
    assert data["run_time"] == "10:30"
    assert data["llm_model"] == "claude-opus-4-7"
    assert data["llm_timeout_seconds"] == 600
    assert data["llm_provider"] == "deepseek-anthropic"
    assert data["llm_base_url"] == "https://api.deepseek.com/anthropic"
    assert data["llm_api_format"] == "anthropic_http"
    assert data["identity"] == {"name": "Alice"}
    assert load_yaml_config(files["config"]).run_time == "10:30"
    [config_bak] = _backups(files["config"])
    assert config_bak.read_text(encoding="utf-8") == _EXISTING_CONFIG

    # rules.yaml: the wizard has no rule questions, so it is left alone.
    assert files["rules"].read_text(encoding="utf-8") == _CUSTOM_RULES
    assert _backups(files["rules"]) == []

    # prompt: re-rendered from the new answers, old one recoverable.
    assert "new@example.com" in files["prompt"].read_text(encoding="utf-8")
    [prompt_bak] = _backups(files["prompt"])
    assert prompt_bak.read_text(encoding="utf-8") == _CUSTOM_PROMPT

    # .env: merged as before, plus a 0600 backup (it holds the token).
    env_content = files["env"].read_text(encoding="utf-8")
    assert "CLAUDE_CODE_OAUTH_TOKEN=preserved-token" in env_content
    assert "USER_CUSTOM_KEY=keep" in env_content
    [env_bak] = _backups(files["env"])
    assert "preserved-token" in env_bak.read_text(encoding="utf-8")
    assert oct(stat.S_IMODE(env_bak.stat().st_mode))[-3:] == "600"


def test_update_unusable_config_falls_back_to_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    _setup_repo(repo_root)
    config_yaml = repo_root / "config" / "config.yaml"
    config_yaml.write_text("- not\n- a mapping\n", encoding="utf-8")

    monkeypatch.setattr("getpass.getpass", lambda _prompt="": "")
    monkeypatch.setattr(builtins, "input", _answer_sequence(["u"] + _minimal_answers()))

    rc = run_init(["--repo-root", str(repo_root)])
    assert rc == 0

    data = yaml.safe_load(config_yaml.read_text(encoding="utf-8"))
    assert data["recipient_email"] == "alice@example.com"
    assert data["llm_model"] == DEFAULT_CLAUDE_MODEL
    [bak] = _backups(config_yaml)
    assert bak.read_text(encoding="utf-8") == "- not\n- a mapping\n"


def test_update_aborted_mid_wizard_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Update-mode backups happen at write time, so Ctrl-C leaves no strays."""
    repo_root = tmp_path / "repo"
    files = _setup_existing_install(repo_root)
    replies = iter(["u", "u", "u", "u", "Alice"])

    def _input(_prompt: str = "") -> str:
        try:
            return next(replies)
        except StopIteration:
            raise KeyboardInterrupt from None

    monkeypatch.setattr(builtins, "input", _input)

    rc = run_init(["--repo-root", str(repo_root)])
    assert rc == 1
    assert files["config"].read_text(encoding="utf-8") == _EXISTING_CONFIG
    assert files["prompt"].read_text(encoding="utf-8") == _CUSTOM_PROMPT
    assert list(repo_root.rglob("*.bak-*")) == []


# ---------------------------------------------------------------------------
# Unit: _render_prompt
# ---------------------------------------------------------------------------

def test_render_prompt_substitution(tmp_path: Path) -> None:
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
# Integration: fresh run writes the four expected files
# ---------------------------------------------------------------------------

def test_fresh_run_writes_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    _setup_repo(repo_root)

    monkeypatch.setattr("getpass.getpass", lambda _prompt="": "tok-valid-token")
    monkeypatch.setattr(builtins, "input", _answer_sequence(_minimal_answers()))

    rc = run_init(["--repo-root", str(repo_root)])
    assert rc == 0

    assert (repo_root / "config" / "config.yaml").exists()
    assert (repo_root / "config" / "rules.yaml").exists()
    assert (repo_root / "prompts" / "hyacine.md").exists()
    env_file = repo_root / ".env"
    assert env_file.exists()

    import yaml

    written = yaml.safe_load((repo_root / "config" / "config.yaml").read_text(encoding="utf-8"))
    assert written["llm_model"] == DEFAULT_CLAUDE_MODEL

    mode = stat.S_IMODE(env_file.stat().st_mode)
    assert oct(mode)[-3:] == "600", f"Expected 600, got {oct(mode)[-3:]}"

    # Directories holding personal data should be 0700.
    for sub in ("config", "prompts", "data"):
        dir_mode = stat.S_IMODE((repo_root / sub).stat().st_mode)
        assert oct(dir_mode)[-3:] == "700", (
            f"Expected {sub}/ 700, got {oct(dir_mode)[-3:]}"
        )

    rendered = (repo_root / "prompts" / "hyacine.md").read_text(encoding="utf-8")
    assert "Alice" in rendered


def test_no_prompt_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    _setup_repo(repo_root)

    called: list[bool] = []

    def _no_getpass(_prompt: str = "") -> str:
        called.append(True)
        return "should-not-be-called"

    monkeypatch.setattr("getpass.getpass", _no_getpass)
    monkeypatch.setattr(builtins, "input", _answer_sequence(_minimal_answers()))

    rc = run_init(["--repo-root", str(repo_root), "--no-prompt-token"])
    assert rc == 0
    assert not called

    env_content = (repo_root / ".env").read_text(encoding="utf-8")
    assert "CLAUDE_CODE_OAUTH_TOKEN=" in env_content


def test_overwrite_backs_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    _setup_repo(repo_root)

    existing = repo_root / "config" / "config.yaml"
    existing.write_text("recipient_email: old@example.com\n", encoding="utf-8")

    monkeypatch.setattr("getpass.getpass", lambda _prompt="": "tok-new")
    monkeypatch.setattr(builtins, "input", _answer_sequence(_minimal_answers()))

    rc = run_init(["--repo-root", str(repo_root), "--overwrite"])
    assert rc == 0

    bak_files = list((repo_root / "config").glob("config.yaml.bak-*"))
    assert bak_files, "Expected a backup file for config.yaml"
    bak_content = bak_files[0].read_text(encoding="utf-8")
    assert "old@example.com" in bak_content

    new_content = existing.read_text(encoding="utf-8")
    assert "alice@example.com" in new_content


def test_skip_all_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    _setup_repo(repo_root)

    # Pre-create all target files
    (repo_root / ".env").write_text("# existing\n", encoding="utf-8")
    (repo_root / "config" / "config.yaml").write_text("# existing\n", encoding="utf-8")
    (repo_root / "config" / "rules.yaml").write_text("# existing\n", encoding="utf-8")
    (repo_root / "prompts" / "hyacine.md").write_text("# existing prompt\n", encoding="utf-8")

    monkeypatch.setattr(builtins, "input", _answer_sequence(["s"]))

    rc = run_init(["--repo-root", str(repo_root)])
    assert rc == 0

    assert (repo_root / "config" / "config.yaml").read_text() == "# existing\n"


def test_bad_timezone_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    _setup_repo(repo_root)

    monkeypatch.setattr("getpass.getpass", lambda _prompt="": "tok-abc")

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

    rc = run_init(["--repo-root", str(repo_root)])
    assert rc == 0

    config_content = (repo_root / "config" / "config.yaml").read_text(encoding="utf-8")
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
