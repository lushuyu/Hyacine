"""Tests for hyacine.llm.claude_code subprocess wrapper."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hyacine.llm.claude_code import (
    ClaudeCodeError,
    build_argv,
    build_env,
    resolve_claude_bin,
    summarize,
)

# ---------------------------------------------------------------------------
# build_env
# ---------------------------------------------------------------------------

class TestBuildEnv:
    def test_scrubs_api_keys(self) -> None:
        base = {
            "CLAUDE_CODE_OAUTH_TOKEN": "oauth-tok",
            "ANTHROPIC_API_KEY": "should-be-removed",
            "ANTHROPIC_AUTH_TOKEN": "also-removed",
            "PATH": "/usr/bin",
        }
        result = build_env(base)
        assert "ANTHROPIC_API_KEY" not in result
        assert "ANTHROPIC_AUTH_TOKEN" not in result
        assert result["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth-tok"
        assert result["PATH"] == "/usr/bin"

    def test_leaves_unrelated_vars(self) -> None:
        base = {
            "CLAUDE_CODE_OAUTH_TOKEN": "tok",
            "HOME": "/home/user",
            "USER": "bob",
        }
        result = build_env(base)
        assert result["HOME"] == "/home/user"
        assert result["USER"] == "bob"

    def test_no_raise_without_oauth_token(self) -> None:
        # build_env intentionally does NOT require CLAUDE_CODE_OAUTH_TOKEN —
        # `claude login` users have their creds in ~/.claude/ or the OS
        # keychain, and the `claude` CLI reads those automatically when no
        # env var is set. Issue #10 softened this path; the API-key scrub
        # is what stays unconditional.
        base = {
            "ANTHROPIC_API_KEY": "key",
            "ANTHROPIC_AUTH_TOKEN": "also-key",
            "PATH": "/usr/bin",
        }
        result = build_env(base)
        assert "ANTHROPIC_API_KEY" not in result
        assert "ANTHROPIC_AUTH_TOKEN" not in result
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in result
        assert result["PATH"] == "/usr/bin"

    def test_does_not_mutate_base(self) -> None:
        base = {
            "CLAUDE_CODE_OAUTH_TOKEN": "tok",
            "ANTHROPIC_API_KEY": "key",
        }
        original = dict(base)
        build_env(base)
        assert base == original

    def test_scrubs_only_present_keys(self) -> None:
        # Only ANTHROPIC_API_KEY present, ANTHROPIC_AUTH_TOKEN absent — should not error
        base = {
            "CLAUDE_CODE_OAUTH_TOKEN": "tok",
            "ANTHROPIC_API_KEY": "key",
        }
        result = build_env(base)
        assert "ANTHROPIC_API_KEY" not in result
        assert "ANTHROPIC_AUTH_TOKEN" not in result

    def test_safe_mode_on_by_default(self) -> None:
        # Keeps the operator's CLAUDE.md / hooks / plugins / MCP servers out
        # of the daily run.
        assert build_env({"PATH": "/usr/bin"})["CLAUDE_CODE_SAFE_MODE"] == "1"

    @pytest.mark.parametrize("value", ["0", "false", "no", "FALSE", " No "])
    def test_safe_mode_opt_out(self, value: str) -> None:
        result = build_env({"HYACINE_CLAUDE_SAFE_MODE": value})
        assert "CLAUDE_CODE_SAFE_MODE" not in result

    @pytest.mark.parametrize("value", ["", "1", "true", "yes"])
    def test_safe_mode_other_values_keep_it_on(self, value: str) -> None:
        result = build_env({"HYACINE_CLAUDE_SAFE_MODE": value})
        assert result["CLAUDE_CODE_SAFE_MODE"] == "1"

    def test_effort_defaults_to_high(self) -> None:
        assert build_env({})["CLAUDE_CODE_EFFORT_LEVEL"] == "high"

    @pytest.mark.parametrize("value", ["low", "medium", "high", "xhigh", "max", " MAX "])
    def test_effort_override(self, value: str) -> None:
        result = build_env({"HYACINE_CLAUDE_EFFORT": value})
        assert result["CLAUDE_CODE_EFFORT_LEVEL"] == value.strip().lower()

    def test_effort_invalid_raises(self) -> None:
        with pytest.raises(ClaudeCodeError, match="HYACINE_CLAUDE_EFFORT"):
            build_env({"HYACINE_CLAUDE_EFFORT": "ultra"})

    def test_explicit_effort_level_wins(self) -> None:
        result = build_env(
            {"CLAUDE_CODE_EFFORT_LEVEL": "low", "HYACINE_CLAUDE_EFFORT": "max"}
        )
        assert result["CLAUDE_CODE_EFFORT_LEVEL"] == "low"


# ---------------------------------------------------------------------------
# build_argv
# ---------------------------------------------------------------------------

class TestBuildArgv:
    def test_argv_shape(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("You are a helpful assistant.")

        argv = build_argv(
            prompt_file,
            "Generate the daily report.",
            model="sonnet",
            max_turns=3,
            permission_mode="plan",
        )

        assert argv[0] == "claude"
        assert "-p" in argv
        assert "--output-format" in argv
        assert "json" in argv
        assert "--model" in argv
        idx_model = argv.index("--model")
        assert argv[idx_model + 1] == "sonnet"
        assert "--max-turns" in argv
        idx_turns = argv.index("--max-turns")
        assert argv[idx_turns + 1] == "3"
        assert "--permission-mode" in argv
        idx_perm = argv.index("--permission-mode")
        assert argv[idx_perm + 1] == "plan"
        assert "--append-system-prompt-file" in argv
        idx_prompt = argv.index("--append-system-prompt-file")
        assert argv[idx_prompt + 1] == str(prompt_file.resolve())
        assert "--no-session-persistence" in argv
        assert "Generate the daily report." in argv

    def test_relative_prompt_path_made_absolute(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # summarize() runs claude from a temp dir, so a relative path would
        # point at nothing there.
        (tmp_path / "prompt.md").write_text("prompt")
        monkeypatch.chdir(tmp_path)
        argv = build_argv(
            Path("prompt.md"), "msg",
            model="sonnet",
            max_turns=3,
            permission_mode="plan",
        )
        value = argv[argv.index("--append-system-prompt-file") + 1]
        assert Path(value).is_absolute()
        assert value == str((tmp_path / "prompt.md").resolve())

    def test_raises_if_prompt_file_missing(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.md"
        with pytest.raises(ClaudeCodeError, match="not found"):
            build_argv(
                missing,
                "msg",
                model="sonnet",
                max_turns=3,
                permission_mode="plan",
            )

    def test_model_parameter_used(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / "p.md"
        prompt_file.write_text("prompt")
        argv = build_argv(
            prompt_file, "msg",
            model="haiku",
            max_turns=5,
            permission_mode="auto",
        )
        idx = argv.index("--model")
        assert argv[idx + 1] == "haiku"
        idx_turns = argv.index("--max-turns")
        assert argv[idx_turns + 1] == "5"


# ---------------------------------------------------------------------------
# resolve_claude_bin
# ---------------------------------------------------------------------------

class TestResolveClaudeBin:
    def _make_fake_claude(self, dir_: Path) -> Path:
        bin_path = dir_ / "claude"
        bin_path.write_text("#!/bin/sh\nexit 0\n")
        bin_path.chmod(0o755)
        return bin_path

    def test_explicit_override_wins(self, tmp_path: Path) -> None:
        bin_path = self._make_fake_claude(tmp_path)
        env = {"HYACINE_CLAUDE_BIN": str(bin_path), "PATH": "/nope"}
        assert resolve_claude_bin(env) == str(bin_path)

    def test_override_not_executable_raises(self, tmp_path: Path) -> None:
        bin_path = tmp_path / "claude"
        bin_path.write_text("not executable")
        env = {"HYACINE_CLAUDE_BIN": str(bin_path), "PATH": "/nope"}
        with pytest.raises(ClaudeCodeError, match="not an executable"):
            resolve_claude_bin(env)

    def test_falls_back_to_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Point HOME at an empty dir so the ~/.local/bin augmentation can't
        # accidentally find the developer's real claude install.
        empty_home = tmp_path / "home"
        empty_home.mkdir()
        monkeypatch.setenv("HOME", str(empty_home))
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        bin_path = self._make_fake_claude(bin_dir)
        env = {"PATH": str(bin_dir)}
        assert resolve_claude_bin(env) == str(bin_path)

    def test_local_bin_augmented(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Simulate ~/.local/bin holding the binary while PATH excludes it —
        # this is the exact systemd default-PATH situation we are guarding against.
        fake_home = tmp_path / "home"
        local_bin = fake_home / ".local" / "bin"
        local_bin.mkdir(parents=True)
        bin_path = self._make_fake_claude(local_bin)
        monkeypatch.setenv("HOME", str(fake_home))
        env = {"PATH": "/usr/bin:/bin"}
        assert resolve_claude_bin(env) == str(bin_path)

    def test_missing_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setenv("HOME", str(empty))
        env = {"PATH": str(empty)}
        with pytest.raises(ClaudeCodeError, match="not found"):
            resolve_claude_bin(env)


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------

class TestSummarize:
    @pytest.fixture(autouse=True)
    def _stub_claude_bin(self, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
        # `summarize()` resolves the claude binary before invoking subprocess.run.
        # CI runners don't have claude installed, so point HYACINE_CLAUDE_BIN at a
        # stub — the mocked subprocess.run never actually executes it.
        stub = tmp_path_factory.mktemp("claude-stub") / "claude"
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)
        monkeypatch.setenv("HYACINE_CLAUDE_BIN", str(stub))
        # Keep the developer's own shell (possibly itself inside Claude Code)
        # from leaking into the env assertions below.
        for var in (
            "HYACINE_CLAUDE_EFFORT",
            "HYACINE_CLAUDE_SAFE_MODE",
            "CLAUDE_CODE_EFFORT_LEVEL",
            "CLAUDE_CODE_SAFE_MODE",
        ):
            monkeypatch.delenv(var, raising=False)

    def test_runs_isolated(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Temp cwd, absolute prompt path, safe mode + pinned effort, no API key."""
        (tmp_path / "prompt.md").write_text("system prompt")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")

        seen: dict[str, object] = {}

        def _fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
            cwd = kwargs["cwd"]
            seen["argv"] = argv
            seen["cwd"] = cwd
            seen["cwd_existed"] = Path(cwd).is_dir()
            seen["cwd_empty"] = not any(Path(cwd).iterdir())
            seen["env"] = kwargs["env"]
            done = MagicMock(spec=subprocess.CompletedProcess)
            done.stdout = b'{"result": "ok", "is_error": false}\n'
            done.stderr = b""
            done.returncode = 0
            return done

        monkeypatch.setattr(subprocess, "run", _fake_run)

        assert summarize("{}", Path("prompt.md")) == "ok"

        cwd = Path(str(seen["cwd"]))
        assert cwd.name.startswith("hyacine-claude-")
        assert cwd != tmp_path
        assert seen["cwd_existed"] and seen["cwd_empty"]
        assert not cwd.exists(), "temp cwd should be cleaned up"

        argv = seen["argv"]
        assert isinstance(argv, list)
        prompt_arg = argv[argv.index("--append-system-prompt-file") + 1]
        assert prompt_arg == str((tmp_path / "prompt.md").resolve())
        assert argv[argv.index("--model") + 1] == "claude-opus-5-5"

        env = seen["env"]
        assert isinstance(env, dict)
        assert env["CLAUDE_CODE_SAFE_MODE"] == "1"
        assert env["CLAUDE_CODE_EFFORT_LEVEL"] == "high"
        assert "ANTHROPIC_API_KEY" not in env

    def test_invalid_effort_raises_before_spawning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("system prompt")
        monkeypatch.setenv("HYACINE_CLAUDE_EFFORT", "turbo")

        def _fail(*a, **kw):  # type: ignore[no-untyped-def]
            raise AssertionError("subprocess.run must not be called")

        monkeypatch.setattr(subprocess, "run", _fail)
        with pytest.raises(ClaudeCodeError, match="HYACINE_CLAUDE_EFFORT"):
            summarize("{}", prompt_file)

    def test_parses_result_field_from_list(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Production path: `claude -p --output-format json` emits a list of events."""
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("system prompt")

        fake_stdout = (
            b'[{"type":"system","subtype":"init"},'
            b'{"type":"assistant","message":{}},'
            b'{"type":"result","subtype":"success","is_error":false,"result":"hello world"}]\n'
        )
        fake_completed = MagicMock(spec=subprocess.CompletedProcess)
        fake_completed.stdout = fake_stdout
        fake_completed.stderr = b""
        fake_completed.returncode = 0

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_completed)
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "fake-oauth-tok")

        result = summarize('{"data": "test"}', prompt_file)
        assert result == "hello world"

    def test_parses_result_field(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("system prompt")

        fake_stdout = b'{"result": "hello world", "is_error": false}\n'
        fake_completed = MagicMock(spec=subprocess.CompletedProcess)
        fake_completed.stdout = fake_stdout
        fake_completed.stderr = b""
        fake_completed.returncode = 0

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_completed)
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "fake-oauth-tok")

        result = summarize(
            '{"data": "test"}',
            prompt_file,
        )
        assert result == "hello world"

    def test_raises_on_timeout(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("system prompt")

        def _raise_timeout(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise subprocess.TimeoutExpired(cmd=["claude"], timeout=300)

        monkeypatch.setattr(subprocess, "run", _raise_timeout)
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "fake-oauth-tok")

        with pytest.raises(ClaudeCodeError, match="timed out"):
            summarize('{"data": "test"}', prompt_file)

    def test_raises_on_error_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("system prompt")

        fake_stdout = b'{"is_error": true, "error": "something went wrong"}\n'
        fake_completed = MagicMock(spec=subprocess.CompletedProcess)
        fake_completed.stdout = fake_stdout
        fake_completed.stderr = b""
        fake_completed.returncode = 1

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_completed)
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "fake-oauth-tok")

        with pytest.raises(ClaudeCodeError, match="error"):
            summarize('{"data": "test"}', prompt_file)

    def test_raises_on_non_json_stdout(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("system prompt")

        fake_completed = MagicMock(spec=subprocess.CompletedProcess)
        fake_completed.stdout = b"not json at all\n"
        fake_completed.stderr = b""
        fake_completed.returncode = 0

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_completed)
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "fake-oauth-tok")

        with pytest.raises(ClaudeCodeError, match="not valid JSON"):
            summarize('{"data": "test"}', prompt_file)

    def test_raises_on_missing_result_field(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("system prompt")

        fake_completed = MagicMock(spec=subprocess.CompletedProcess)
        fake_completed.stdout = b'{"some_other_field": "value"}\n'
        fake_completed.stderr = b""
        fake_completed.returncode = 0

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_completed)
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "fake-oauth-tok")

        with pytest.raises(ClaudeCodeError, match="missing 'result'"):
            summarize('{"data": "test"}', prompt_file)

    def test_raises_on_empty_stdout(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("system prompt")

        fake_completed = MagicMock(spec=subprocess.CompletedProcess)
        fake_completed.stdout = b""
        fake_completed.stderr = b"some stderr"
        fake_completed.returncode = 1

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_completed)
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "fake-oauth-tok")

        with pytest.raises(ClaudeCodeError, match="no stdout"):
            summarize('{"data": "test"}', prompt_file)
