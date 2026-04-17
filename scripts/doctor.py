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

import yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _xdg_config_home() -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME", "")
    return Path(raw) if raw else Path.home() / ".config"


def _xdg_state_home() -> Path:
    raw = os.environ.get("XDG_STATE_HOME", "")
    return Path(raw) if raw else Path.home() / ".local" / "state"


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


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

Check = tuple[str, str, str]  # (status, label, detail)


def check_config_dir(config_dir: Path) -> Check:
    label = f"XDG config dir exists at {config_dir} (mode 0700)"
    if not config_dir.exists():
        return FAIL, label, "Directory missing — run: python -m hyacine init"
    mode = _file_mode_octal(config_dir)
    if mode != "700":
        return WARN, label, f"Mode is {mode}; expected 700 (hyacine.env inside)"
    return PASS, label, ""


def check_env_file(env_file: Path) -> Check:
    label = "hyacine.env exists (mode 0600)"
    if not env_file.exists():
        return FAIL, label, "Missing — run: python -m hyacine init"
    mode = _file_mode_octal(env_file)
    if mode != "600":
        return WARN, label, f"Mode is {mode}; expected 600 for security"
    return PASS, label, ""


def check_oauth_token() -> Check:
    label = "CLAUDE_CODE_OAUTH_TOKEN is set and not a placeholder"
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    if not token:
        return FAIL, label, "Not set — add to ~/.config/hyacine/hyacine.env"
    if "replace" in token.lower() or token.startswith("sk-") and len(token) < 20:
        return FAIL, label, "Token looks like a placeholder"
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
    label = "config.yaml exists + parses"
    if not config_yaml.exists():
        return FAIL, label, "Missing — run: python -m hyacine init"
    try:
        with config_yaml.open(encoding="utf-8") as f:
            yaml.safe_load(f)
        return PASS, label, ""
    except yaml.YAMLError as exc:
        return FAIL, label, f"Parse error: {exc}"


def check_rules_yaml(rules_yaml: Path) -> Check:
    label = "rules.yaml exists + parses"
    if not rules_yaml.exists():
        return FAIL, label, "Missing — run: python -m hyacine init"
    try:
        with rules_yaml.open(encoding="utf-8") as f:
            yaml.safe_load(f)
        return PASS, label, ""
    except yaml.YAMLError as exc:
        return FAIL, label, f"Parse error: {exc}"


def check_prompt_md(prompt_md: Path, config_yaml: Path) -> Check:
    label = "prompts/briefing.md exists and references operator name"
    if not prompt_md.exists():
        return FAIL, label, "Missing — run: python -m hyacine init"

    content = prompt_md.read_text(encoding="utf-8")

    # Sanity: rendered file should not contain Jinja delimiters (unrendered)
    if "{{" in content or "{%" in content:
        return WARN, label, "File may contain unrendered Jinja placeholders"
    if not content.strip():
        return FAIL, label, "File is empty — run: python -m hyacine init"
    return PASS, label, ""


def check_state_dir(state_dir: Path) -> Check:
    label = f"XDG state dir exists at {state_dir} (mode 0700)"
    if not state_dir.exists():
        return FAIL, label, "Directory missing — run: python -m hyacine init"
    mode = _file_mode_octal(state_dir)
    if mode != "700":
        return WARN, label, f"Mode is {mode}; expected 700"
    return PASS, label, ""


def check_db(state_dir: Path) -> Check:
    db_path = state_dir / "hyacine.db"
    label = f"hyacine.db exists at {db_path}"
    if not db_path.exists():
        return WARN, label, "Not yet created — will be created on first run (OK)"
    return PASS, label, ""


def check_auth_record(state_dir: Path) -> Check:
    # auth_record may be in auth/ subdir
    auth_record = state_dir / "auth" / "auth_record.json"
    if not auth_record.exists():
        auth_record = state_dir / "auth_record.json"

    label = "auth_record.json exists (mode 0600)"
    if not auth_record.exists():
        return WARN, label, "Not found — run: python scripts/bootstrap_auth.py"
    mode = _file_mode_octal(auth_record)
    if mode != "600":
        return WARN, label, f"Mode is {mode}; expected 600"
    return PASS, label, ""


def check_claude_cli() -> Check:
    label = "`claude` CLI is reachable"
    claude_path = shutil.which("claude")
    if not claude_path:
        return FAIL, label, "Not found in PATH — install Claude Code CLI"
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        version_line = (result.stdout or result.stderr or "").splitlines()[0] if (
            result.stdout or result.stderr
        ) else "unknown"
        return PASS, label, f"version: {version_line}"
    except Exception as exc:
        return WARN, label, f"Found but failed to run: {exc}"


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
        if result.returncode in (0, 3):  # 3 = no active units, still usable
            return PASS, label, ""
        return WARN, label, "systemctl --user returned non-zero (may be WSL)"
    except Exception as exc:
        return WARN, label, f"Could not run: {exc}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_checks(
    config_dir: Path | None = None,
    state_dir: Path | None = None,
) -> int:
    """Run all checks. Returns exit code (0/1/2)."""
    if config_dir is None:
        config_dir = _xdg_config_home() / "hyacine"
    if state_dir is None:
        state_dir = _xdg_state_home() / "hyacine"

    env_file = config_dir / "hyacine.env"
    config_yaml = config_dir / "config.yaml"
    rules_yaml = config_dir / "rules.yaml"
    prompt_md = config_dir / "prompts" / "hyacine.md"

    checks: list[Check] = [
        check_config_dir(config_dir),
        check_env_file(env_file),
        check_oauth_token(),
        check_conflicting_keys(),
        check_config_yaml(config_yaml),
        check_rules_yaml(rules_yaml),
        check_prompt_md(prompt_md, config_yaml),
        check_state_dir(state_dir),
        check_db(state_dir),
        check_auth_record(state_dir),
        check_claude_cli(),
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
        print("\033[32mAll checks passed.\033[0m")
        return 0
    if max_status == WARN:
        print("\033[33mOne or more warnings. Review the items marked [!] above.\033[0m")
        return 1
    print("\033[31mOne or more hard failures. Fix the items marked [!] above.\033[0m")
    return 2


def main(argv: list[str] | None = None) -> int:
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        prog="doctor",
        description="hyacine post-install health check.",
    )
    parser.add_argument(
        "--config-dir",
        metavar="PATH",
        help="Override XDG config directory.",
    )
    parser.add_argument(
        "--state-dir",
        metavar="PATH",
        help="Override XDG state directory.",
    )
    args = parser.parse_args(argv)

    config_dir = Path(args.config_dir).expanduser() if args.config_dir else None
    state_dir = Path(args.state_dir).expanduser() if args.state_dir else None

    return run_checks(config_dir=config_dir, state_dir=state_dir)


if __name__ == "__main__":
    sys.exit(main())
