"""Post-install health check for hyacine.

Usage:
    python scripts/doctor.py

Exit codes:
    0  — all checks green
    1  — one or more warnings (non-critical)
    2  — one or more hard failures
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import yaml
from pydantic import ValidationError

if TYPE_CHECKING:
    from hyacine.llm.providers import Provider

_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_RESET = "\033[0m"

PASS = "pass"
WARN = "warn"
FAIL = "fail"


def _fmt(status: str, message: str) -> str:
    if status == PASS:
        return f"{_GREEN}[x]{_RESET} {message}"
    if status == WARN:
        return f"{_YELLOW}[!]{_RESET} {message}"
    return f"{_RED}[!]{_RESET} {message}"


def _file_mode_octal(path: Path) -> str:
    return oct(stat.S_IMODE(path.stat().st_mode))[-3:]


Check = tuple[str, str, str]  # (status, label, detail)


def _read_env_file(env_file: Path | None) -> dict[str, str]:
    """Parse *env_file* with python-dotenv, the parser pydantic-settings uses.

    Only systemd's ``EnvironmentFile=`` exports .env into a process
    environment, so a check that reads os.environ alone misses values the
    timer run does get. Empty values count as unset.
    """
    if env_file is None or not env_file.is_file():
        return {}
    from dotenv import dotenv_values  # noqa: PLC0415

    return {k: v for k, v in dotenv_values(env_file).items() if v}


def _looks_like_placeholder(value: str) -> bool:
    return "replace" in value.lower() or value.startswith("sk-") and len(value) < 20


def _env_source_verdict(
    key: str,
    env_file: Path | None,
    timer_without: str,
    *,
    check_placeholder: bool = True,
) -> tuple[str, str] | None:
    """Judge *key* as each run path sees it; None when neither source sets it.

    The systemd timer gets *key* only from .env (EnvironmentFile=; the user
    manager doesn't inherit shell rc exports), while a manual
    `python -m hyacine run` gets only the shell's value. So .env is checked
    first, a bad value in either source fails, and a shell value .env lacks
    or contradicts warns. *timer_without* says what a scheduled run does when
    only the shell sets *key*. With env_file None there's no .env to compare.
    """
    target = str(env_file) if env_file is not None else ".env"
    file_val = _read_env_file(env_file).get(key, "")
    shell_val = os.environ.get(key, "")
    if check_placeholder and file_val and _looks_like_placeholder(file_val):
        return FAIL, f"{key} in {target} looks like a placeholder — the systemd timer uses this value"
    if check_placeholder and shell_val and _looks_like_placeholder(shell_val):
        return FAIL, (
            f"{key} in the shell environment looks like a placeholder — a manual "
            "`python -m hyacine run` uses this value"
        )
    if file_val and shell_val:
        if file_val != shell_val:
            return WARN, (
                f"{target} and the shell export differ — the systemd timer uses {target}, "
                "a manual `python -m hyacine run` uses the shell value"
            )
        return PASS, ""
    if file_val:
        return PASS, (
            f"Read from {target}; systemd loads it via EnvironmentFile=. For a manual "
            f"`python -m hyacine run`, export it first: set -a; . {target}; set +a"
        )
    if shell_val:
        if env_file is None:
            return PASS, ""
        return WARN, (
            f"Set only in the shell — the systemd timer reads {target}, which lacks it, "
            f"so {timer_without}. Add {key}=... to {target}"
        )
    return None


def _one_line(exc: BaseException) -> str:
    """Collapse a multi-line pydantic / loader error into one detail line."""
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '(top level)'}: {err['msg']}"
            for err in exc.errors()
        )
    return " ".join(str(exc).split())


def _non_cli_provider(config_yaml: Path) -> Provider | None:
    """Return the provider when config.yaml picks one that doesn't run `claude`.

    Resolves like the pipeline does, so an empty or unknown llm_provider
    means the claude-code-oauth default and returns None. A config.yaml that
    doesn't load also returns None — check_config_yaml reports that.
    """
    from hyacine.config import load_yaml_config  # noqa: PLC0415
    from hyacine.llm.providers import resolve  # noqa: PLC0415

    try:
        cfg = load_yaml_config(config_yaml)
    except Exception:
        return None
    provider = resolve(
        provider_id=cfg.llm_provider,
        api_format=cfg.llm_api_format,
        base_url=cfg.llm_base_url,
    )
    return None if provider.api_format == "anthropic_cli" else provider


def _is_local_endpoint(provider: Provider) -> bool:
    """Ollama-style presets and loopback URLs serve without an API key."""
    host = urlparse(provider.base_url).hostname or ""
    return provider.category == "local" or host in ("localhost", "127.0.0.1", "::1")


def check_env_file(env_file: Path) -> Check:
    label = f".env exists at {env_file} (mode 0600)"
    if not env_file.exists():
        return FAIL, label, "Missing — run: python -m hyacine init"
    mode = _file_mode_octal(env_file)
    if mode != "600":
        return WARN, label, f"Mode is {mode}; expected 600 for security"
    return PASS, label, ""


def check_oauth_token(env_file: Path | None = None) -> Check:
    label = "CLAUDE_CODE_OAUTH_TOKEN is set and not a placeholder"
    target = str(env_file) if env_file is not None else ".env"
    verdict = _env_source_verdict(
        "CLAUDE_CODE_OAUTH_TOKEN",
        env_file,
        "scheduled runs fall back to `claude login` credentials, if there are any",
    )
    if verdict is not None:
        return verdict[0], label, verdict[1]
    # The token is optional: without it `claude` uses its own
    # `claude login` credentials (see llm.claude_code.build_env).
    credentials = Path.home() / ".claude" / ".credentials.json"
    if credentials.exists():
        return WARN, label, (
            f"Not set — `claude` will fall back to its `claude login` credentials "
            f"({credentials}). Add CLAUDE_CODE_OAUTH_TOKEN=... to {target} to pin a token"
        )
    return FAIL, label, f"Not set — add CLAUDE_CODE_OAUTH_TOKEN=... to {target}"


def check_llm_api_key(env_file: Path | None, provider: Provider) -> Check:
    """The key pipeline.run sends to an HTTP provider (anthropic_http / openai_chat)."""
    target = str(env_file) if env_file is not None else ".env"
    local = _is_local_endpoint(provider)
    if local:
        label = f"HYACINE_LLM_API_KEY for llm_provider {provider.id!r} (optional: local endpoint)"
    else:
        label = f"HYACINE_LLM_API_KEY is set for llm_provider {provider.id!r}"
    verdict = _env_source_verdict(
        "HYACINE_LLM_API_KEY",
        env_file,
        "scheduled runs send no key",
        # Local servers ignore the key, so a dummy like "sk-no-key" is fine.
        check_placeholder=not local,
    )
    if verdict is not None:
        return verdict[0], label, verdict[1]
    if local:
        return PASS, label, f"Not set — not needed for {provider.base_url}"
    if provider.category == "custom":
        return WARN, label, (
            f"Not set — fine only if {provider.base_url} accepts requests without a key; "
            f"otherwise add HYACINE_LLM_API_KEY=... to {target}"
        )
    return FAIL, label, (
        f"Not set — add HYACINE_LLM_API_KEY=... to {target}; every run would fail with HTTP 401"
    )


def check_conflicting_keys() -> Check:
    label = "ANTHROPIC_API_KEY and ANTHROPIC_AUTH_TOKEN are unset"
    keys = [k for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN") if os.environ.get(k)]
    if keys:
        return WARN, label, (
            f"{', '.join(keys)} is set — this may silently hijack Claude Code auth. "
            "Unset unless you know what you're doing."
        )
    return PASS, label, ""


def check_config_yaml(config_yaml: Path) -> Check:
    label = f"config.yaml exists and is valid at {config_yaml}"
    if not config_yaml.exists():
        return FAIL, label, "Missing — run: python -m hyacine init"
    from hyacine.config import load_yaml_config  # noqa: PLC0415

    # Load it the way the pipeline does: a file that merely parses can still
    # fail every run in _get_cfg(), or before the first send.
    try:
        cfg = load_yaml_config(config_yaml)
    except yaml.YAMLError as exc:
        return FAIL, label, f"Parse error: {exc}"
    except ValidationError as exc:
        hint = ""
        if any(err["loc"] == ("run_time",) for err in exc.errors()):
            hint = ' (quote it: run_time: "10:30" — unquoted, YAML reads 10:30 as the number 630)'
        return FAIL, label, f"Schema error: {_one_line(exc)}{hint}"
    except TypeError as exc:
        return FAIL, label, f"Schema error — expected key: value pairs at the top level: {exc}"
    except (OSError, ValueError) as exc:
        return FAIL, label, f"Could not load: {_one_line(exc)}"
    if not cfg.recipient_email.strip():
        return FAIL, label, "recipient_email is empty — every run aborts before sending"
    try:
        ZoneInfo(cfg.timezone)
    except (KeyError, ValueError, OSError) as exc:
        return FAIL, label, (
            f"timezone {cfg.timezone!r} is not a valid IANA zone (e.g. UTC, "
            f"Asia/Singapore) — every run aborts: {exc}"
        )
    return PASS, label, ""


def check_rules_yaml(rules_yaml: Path) -> Check:
    label = f"rules.yaml exists and is valid at {rules_yaml}"
    if not rules_yaml.exists():
        return FAIL, label, "Missing — run: python -m hyacine init"
    from hyacine.pipeline.rules import load_rules  # noqa: PLC0415

    # The pipeline uses load_rules() too; when it raises, the run classifies
    # every email without rules, so one bad entry silently disables them all.
    try:
        load_rules(rules_yaml)
    except yaml.YAMLError as exc:
        return FAIL, label, f"Parse error: {exc}"
    except OSError as exc:
        return FAIL, label, f"Could not read: {exc}"
    except ValueError as exc:
        cause = exc.__cause__
        reason = _one_line(cause if isinstance(cause, ValidationError) else exc)
        return FAIL, label, f"Schema error — the pipeline will ignore every rule: {reason}"
    return PASS, label, ""


def check_prompt_md(prompt_md: Path) -> Check:
    label = f"prompts/hyacine.md exists at {prompt_md}"
    if not prompt_md.exists():
        return FAIL, label, "Missing — run: python -m hyacine init"

    content = prompt_md.read_text(encoding="utf-8")
    if "{{" in content or "{%" in content:
        return WARN, label, "File may contain unrendered Jinja placeholders"
    if not content.strip():
        return FAIL, label, "File is empty — run: python -m hyacine init"
    return PASS, label, ""


def check_data_dir(data_dir: Path) -> Check:
    label = f"data dir exists at {data_dir}"
    if not data_dir.exists():
        return WARN, label, "Not yet created — will be created on first run (OK)"
    return PASS, label, ""


def check_db(db_path: Path) -> Check:
    label = f"hyacine.db exists at {db_path}"
    if not db_path.exists():
        return WARN, label, "Not yet created — will be created on first run (OK)"
    return PASS, label, ""


def check_auth_record(auth_record: Path) -> Check:
    """*auth_record* is Settings.auth_record_path, the file bootstrap_auth writes."""
    label = f"Graph auth record exists at {auth_record} (mode 0600)"
    if not auth_record.exists():
        return WARN, label, "Not found — run: python scripts/bootstrap_auth.py"
    mode = _file_mode_octal(auth_record)
    if mode != "600":
        return WARN, label, f"Mode is {mode}; expected 600"
    return PASS, label, ""


def check_claude_cli(env_file: Path | None = None, non_cli_provider: str = "") -> Check:
    label = "`claude` CLI is reachable"
    if non_cli_provider:
        return PASS, "`claude` CLI (not used)", (
            f"Not needed — llm_provider {non_cli_provider!r} doesn't use the claude CLI"
        )
    from hyacine.llm.claude_code import ClaudeCodeError, resolve_claude_bin  # noqa: PLC0415

    # Resolve like the timer run: HYACINE_CLAUDE_BIN from .env (systemd's
    # EnvironmentFile=, which beats the shell's), then PATH plus ~/.local/bin.
    target = str(env_file) if env_file is not None else ".env"
    env = dict(os.environ)
    file_bin = _read_env_file(env_file).get("HYACINE_CLAUDE_BIN", "")
    shell_bin = env.get("HYACINE_CLAUDE_BIN", "")
    if file_bin:
        env["HYACINE_CLAUDE_BIN"] = file_bin
    try:
        claude_path = resolve_claude_bin(env)
    except ClaudeCodeError as exc:
        if file_bin:
            return FAIL, label, f"{exc} Set in {target} — the systemd timer uses this value"
        return FAIL, label, str(exc)
    # A manual `python -m hyacine run` resolves the shell's value instead.
    mismatch = ""
    if file_bin and shell_bin and shell_bin != file_bin:
        try:
            shell_path = resolve_claude_bin({**env, "HYACINE_CLAUDE_BIN": shell_bin})
        except ClaudeCodeError as exc:
            return FAIL, label, (
                f"{exc} Set in the shell environment — a manual `python -m hyacine run` "
                "uses this value"
            )
        if shell_path != claude_path:
            mismatch = (
                f"HYACINE_CLAUDE_BIN in {target} and the shell export ({shell_path}) differ "
                f"— the systemd timer uses {target}, a manual `python -m hyacine run` uses "
                "the shell value"
            )
    elif shell_bin and not file_bin and env_file is not None:
        mismatch = (
            f"HYACINE_CLAUDE_BIN is set only in the shell — the systemd timer reads "
            f"{target}, which lacks it, so scheduled runs look `claude` up on PATH. "
            f"Add HYACINE_CLAUDE_BIN=... to {target}"
        )
    try:
        result = subprocess.run(
            [claude_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        return WARN, label, f"Found at {claude_path} but failed to run: {exc}"
    output = (result.stdout or result.stderr or "").strip()
    version_line = output.splitlines()[0] if output else "unknown"
    if result.returncode != 0:
        return WARN, label, (
            f"{claude_path} --version exited {result.returncode}: {version_line}"
        )
    if mismatch:
        return WARN, label, f"version: {version_line} ({claude_path}). {mismatch}"
    return PASS, label, f"version: {version_line} ({claude_path})"


def check_systemctl() -> Check:
    label = "`systemctl --user` is usable (informational)"
    if shutil.which("systemctl") is None:
        return WARN, label, "systemctl not found — OK on WSL / non-systemd hosts"
    try:
        result = subprocess.run(
            ["systemctl", "--user", "status"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode in (0, 3):
            return PASS, label, ""
        return WARN, label, "systemctl --user returned non-zero (may be WSL)"
    except Exception as exc:
        return WARN, label, f"Could not run: {exc}"


def run_checks() -> int:
    """Run all checks. Returns exit code (0/1/2)."""
    from hyacine.config import Settings, _default_repo_root  # noqa: PLC0415

    settings = Settings()
    # Anchor the .env path at the same repo root Settings uses (respecting
    # HYACINE_REPO_ROOT), so `python scripts/doctor.py` from any CWD looks
    # at the same file the runtime will actually read.
    env_file = _default_repo_root() / ".env"
    # The token and CLI checks only apply when the claude CLI does the LLM
    # call; an HTTP provider needs HYACINE_LLM_API_KEY instead.
    provider = _non_cli_provider(settings.config_path)

    checks: list[Check] = [
        check_env_file(env_file),
        check_oauth_token(env_file) if provider is None else check_llm_api_key(env_file, provider),
        check_conflicting_keys(),
        check_config_yaml(settings.config_path),
        check_rules_yaml(settings.rules_path),
        check_prompt_md(settings.prompt_path),
        check_data_dir(settings.db_path.parent),
        check_db(settings.db_path),
        check_auth_record(settings.auth_record_path),
        check_claude_cli(env_file, provider.id if provider is not None else ""),
        check_systemctl(),
    ]

    max_status = PASS
    for status, label, detail in checks:
        line = _fmt(status, label)
        if detail:
            line += f"\n     {detail}"
        print(line)
        if status == FAIL:
            max_status = FAIL
        elif status == WARN and max_status == PASS:
            max_status = WARN

    print()
    if max_status == PASS:
        print(f"{_GREEN}All checks passed.{_RESET}")
        return 0
    if max_status == WARN:
        print(f"{_YELLOW}One or more warnings. Review the items marked [!] above.{_RESET}")
        return 1
    print(f"{_RED}One or more hard failures. Fix the items marked [!] above.{_RESET}")
    return 2


def main(argv: list[str] | None = None) -> int:
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        prog="doctor",
        description="hyacine post-install health check.",
    )
    parser.parse_args(argv)
    return run_checks()


if __name__ == "__main__":
    sys.exit(main())
