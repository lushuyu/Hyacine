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
from zoneinfo import ZoneInfo

import yaml
from pydantic import ValidationError

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


def _one_line(exc: BaseException) -> str:
    """Collapse a multi-line pydantic / loader error into one detail line."""
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '(top level)'}: {err['msg']}"
            for err in exc.errors()
        )
    return " ".join(str(exc).split())


def _non_cli_provider(config_yaml: Path) -> str:
    """Return the provider id when config.yaml picks one that doesn't run `claude`.

    Resolves like the pipeline does, so an empty or unknown llm_provider
    means the claude-code-oauth default and returns "". A config.yaml that
    doesn't load also returns "" — check_config_yaml reports that.
    """
    from hyacine.config import load_yaml_config  # noqa: PLC0415
    from hyacine.llm.providers import resolve  # noqa: PLC0415

    try:
        cfg = load_yaml_config(config_yaml)
    except Exception:
        return ""
    provider = resolve(
        provider_id=cfg.llm_provider,
        api_format=cfg.llm_api_format,
        base_url=cfg.llm_base_url,
    )
    return "" if provider.api_format == "anthropic_cli" else provider.id


def check_env_file(env_file: Path) -> Check:
    label = f".env exists at {env_file} (mode 0600)"
    if not env_file.exists():
        return FAIL, label, "Missing — run: python -m hyacine init"
    mode = _file_mode_octal(env_file)
    if mode != "600":
        return WARN, label, f"Mode is {mode}; expected 600 for security"
    return PASS, label, ""


def check_oauth_token(env_file: Path | None = None, non_cli_provider: str = "") -> Check:
    label = "CLAUDE_CODE_OAUTH_TOKEN is set and not a placeholder"
    if non_cli_provider:
        return PASS, label, f"Not needed — llm_provider {non_cli_provider!r} doesn't use the claude CLI"
    target = str(env_file) if env_file is not None else ".env"
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    from_env_file = False
    if not token:
        token = _read_env_file(env_file).get("CLAUDE_CODE_OAUTH_TOKEN", "")
        from_env_file = bool(token)
    if not token:
        # The token is optional: without it `claude` uses its own
        # `claude login` credentials (see llm.claude_code.build_env).
        credentials = Path.home() / ".claude" / ".credentials.json"
        if credentials.exists():
            return WARN, label, (
                f"Not set — `claude` will fall back to its `claude login` credentials "
                f"({credentials}). Add CLAUDE_CODE_OAUTH_TOKEN=... to {target} to pin a token"
            )
        return FAIL, label, f"Not set — add CLAUDE_CODE_OAUTH_TOKEN=... to {target}"
    if "replace" in token.lower() or token.startswith("sk-") and len(token) < 20:
        return FAIL, label, "Token looks like a placeholder"
    if from_env_file:
        return PASS, label, (
            f"Read from {target}; systemd loads it via EnvironmentFile=. For a manual "
            f"`python -m hyacine run`, export it first: set -a; . {target}; set +a"
        )
    return PASS, label, ""


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


def check_auth_record(auth_dir: Path) -> Check:
    auth_record = auth_dir / "auth_record.json"
    label = f"auth_record.json exists at {auth_record} (mode 0600)"
    if not auth_record.exists():
        return WARN, label, "Not found — run: python scripts/bootstrap_auth.py"
    mode = _file_mode_octal(auth_record)
    if mode != "600":
        return WARN, label, f"Mode is {mode}; expected 600"
    return PASS, label, ""


def check_claude_cli(env_file: Path | None = None, non_cli_provider: str = "") -> Check:
    label = "`claude` CLI is reachable"
    if non_cli_provider:
        return PASS, label, f"Not needed — llm_provider {non_cli_provider!r} doesn't use the claude CLI"
    from hyacine.llm.claude_code import ClaudeCodeError, resolve_claude_bin  # noqa: PLC0415

    # Resolve like the pipeline: HYACINE_CLAUDE_BIN (the timer run gets it
    # from .env), then PATH plus ~/.local/bin.
    env = dict(os.environ)
    override = _read_env_file(env_file).get("HYACINE_CLAUDE_BIN")
    if override and not env.get("HYACINE_CLAUDE_BIN"):
        env["HYACINE_CLAUDE_BIN"] = override
    try:
        claude_path = resolve_claude_bin(env)
    except ClaudeCodeError as exc:
        return FAIL, label, str(exc)
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
    # The token and CLI checks only apply when the claude CLI does the LLM call.
    non_cli_provider = _non_cli_provider(settings.config_path)

    checks: list[Check] = [
        check_env_file(env_file),
        check_oauth_token(env_file, non_cli_provider),
        check_conflicting_keys(),
        check_config_yaml(settings.config_path),
        check_rules_yaml(settings.rules_path),
        check_prompt_md(settings.prompt_path),
        check_data_dir(settings.db_path.parent),
        check_db(settings.db_path),
        check_auth_record(settings.auth_dir),
        check_claude_cli(env_file, non_cli_provider),
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
