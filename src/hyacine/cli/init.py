"""Interactive setup wizard for hyacine.

Entry point: ``python -m hyacine init [--config-dir PATH] [--overwrite] [--no-prompt-token]``

Flow:
  1. Resolve XDG config/state dirs.
  2. Ensure directories exist.
  3. Idempotency check on each target file.
  4. Collect answers from the user.
  5. Render prompts/briefing.md from Jinja2 template.
  6. Write config.yaml, rules.yaml, hyacine.env.
  7. Print summary + next steps.
"""
from __future__ import annotations

import argparse
import getpass
import os
import re
import shutil
import subprocess
import textwrap
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from jinja2 import Environment, FileSystemLoader

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _xdg_config_home() -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME", "")
    return Path(raw) if raw else Path.home() / ".config"


def _xdg_state_home() -> Path:
    raw = os.environ.get("XDG_STATE_HOME", "")
    return Path(raw) if raw else Path.home() / ".local" / "state"


def _green(text: str) -> str:
    return f"\033[32m{text}\033[0m"


def _yellow(text: str) -> str:
    return f"\033[33m{text}\033[0m"


def _red(text: str) -> str:
    return f"\033[31m{text}\033[0m"


def _ask(
    prompt: str,
    default: str | None = None,
    validate: Callable[[str], None] | None = None,
) -> str:
    """Print a prompt and read one line from stdin.

    If *default* is provided it is shown in brackets and returned when the
    user submits an empty line.  *validate* may be a callable that raises
    ``ValueError`` with a human-readable message on bad input.
    """
    display = f"{prompt}"
    if default is not None:
        display += f" [{default}]"
    display += ": "

    while True:
        try:
            raw = input(display)
        except EOFError:
            raw = ""
        value = raw.strip() or (default or "")
        if validate is not None:
            try:
                validate(value)
            except ValueError as exc:
                print(_red(f"  Error: {exc}"))
                continue
        return value


def _ask_multiline(prompt: str) -> str:
    """Read lines until a blank line or EOF."""
    print(f"{prompt} (blank line to finish):")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "":
            break
        lines.append(line)
    return "\n".join(lines)


def _validate_tz(value: str) -> None:
    if not value:
        raise ValueError("timezone cannot be empty")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, KeyError) as exc:
        raise ValueError(f"'{value}' is not a valid IANA timezone (e.g. America/New_York, UTC)") from exc


def _validate_time(value: str) -> None:
    if not re.match(r"^\d{2}:\d{2}$", value):
        raise ValueError("expected HH:MM format")
    h, m = value.split(":")
    if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
        raise ValueError("time out of range")


def _validate_language(value: str) -> None:
    if value not in ("en", "zh-CN"):
        raise ValueError("must be 'en' or 'zh-CN'")


def _looks_like_uuid(value: str) -> bool:
    return bool(re.match(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        value,
        re.IGNORECASE,
    ))


def _backup_path(p: Path) -> Path:
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return p.with_name(f"{p.name}.bak-{ts}")


def _repo_root() -> Path:
    """Return the directory containing this file's package root (repo root)."""
    # src/hyacine/cli/init.py → src/hyacine/cli → src/hyacine → src → repo_root
    return Path(__file__).parent.parent.parent.parent


# ---------------------------------------------------------------------------
# File idempotency resolution
# ---------------------------------------------------------------------------

RESOLUTION_SKIP = "skip"
RESOLUTION_UPDATE = "update"
RESOLUTION_OVERWRITE = "overwrite"
RESOLUTION_QUIT = "quit"


def _resolve_existing(path: Path, overwrite: bool) -> str:
    """Return a resolution string for a file that already exists."""
    if overwrite:
        bak = _backup_path(path)
        shutil.copy2(path, bak)
        print(f"  Backed up {path} → {bak}")
        return RESOLUTION_OVERWRITE

    print(f"\n{_yellow('File exists')}: {path}")
    while True:
        try:
            choice = input("  [u]pdate / [b]ackup & overwrite / [s]kip all / [q]uit: ").strip().lower()
        except EOFError:
            choice = "s"
        if choice == "u":
            return RESOLUTION_UPDATE
        if choice == "b":
            bak = _backup_path(path)
            shutil.copy2(path, bak)
            print(f"  Backed up → {bak}")
            return RESOLUTION_OVERWRITE
        if choice == "s":
            return RESOLUTION_SKIP
        if choice == "q":
            return RESOLUTION_QUIT
        print("  Please enter u, b, s, or q.")


# ---------------------------------------------------------------------------
# Default categories markdown block
# ---------------------------------------------------------------------------

_DEFAULT_CATEGORIES_MD = textwrap.dedent("""\
    - **Priority senders** — direct messages from manager / key stakeholders
    - **Action required** — emails containing clear action requests or deadlines
    - **Meeting invites** — calendar invitations, schedule changes
    - **Project updates** — status updates, milestones, blockers
    - **External partners** — clients, vendors, collaborators
    - **Newsletters** — industry digests, mailing lists
    - **Receipts / finance** — invoices, payment confirmations
    - **GitHub / CI** — code review requests, build failures, PR notifications
    - **Marketing** — promotions, product announcements
    - **Other** — everything else\
""")


# ---------------------------------------------------------------------------
# Main wizard
# ---------------------------------------------------------------------------

def _collect_answers(args: argparse.Namespace) -> dict[str, object]:  # noqa: C901
    """Interactively collect all wizard fields; return a dict."""
    print("\n" + "=" * 60)
    print("  hyacine setup wizard")
    print("  Press Ctrl-C to abort at any time.")
    print("=" * 60 + "\n")

    answers: dict[str, object] = {}

    # 1. Operator name
    answers["name"] = _ask("Your display name (e.g. Alice)")

    # 2. Operator role
    answers["role"] = _ask("Your role (e.g. PM at Acme Robotics)")

    # 3. Identity blurb
    print()
    answers["identity_blurb"] = _ask_multiline(
        "Identity blurb — 1-3 sentences about yourself, focus areas, research interests"
    )

    # 4. Priorities (at least 1, at most 10)
    print("\nPriority signals — what should trigger the 'must-do today' category?")
    priorities: list[str] = []
    while len(priorities) < 10:
        p = _ask(f"  Add priority ({len(priorities)}/10; blank to finish)" if priorities else "  Add priority (at least 1)")
        if not p:
            if not priorities:
                print(_red("  You must add at least one priority."))
                continue
            break
        priorities.append(p)
    answers["priorities"] = priorities

    # 5. Category hints
    print("\nCategory hints — a default set is provided. Accept or edit?")
    print(_DEFAULT_CATEGORIES_MD)
    while True:
        try:
            choice = input("\n  [A]ccept default / [E]dit in $EDITOR: ").strip().lower()
        except EOFError:
            choice = "a"
        if choice in ("a", ""):
            answers["categories_md"] = _DEFAULT_CATEGORIES_MD
            break
        if choice == "e":
            editor = os.environ.get("EDITOR", "nano")
            import tempfile  # noqa: PLC0415
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(_DEFAULT_CATEGORIES_MD)
                tmp_name = tmp.name
            try:
                subprocess.run([editor, tmp_name], check=False)
                answers["categories_md"] = Path(tmp_name).read_text(encoding="utf-8").strip()
            finally:
                Path(tmp_name).unlink(missing_ok=True)
            break
        print("  Please enter A or E.")

    # 6. Email recipient
    answers["email_recipient"] = _ask("Email recipient (where the daily briefing is sent)")

    # 7. Timezone
    answers["timezone"] = _ask("Timezone (IANA, e.g. America/New_York)", default="UTC", validate=_validate_tz)

    # 8. Language
    answers["language"] = _ask("Language (en / zh-CN)", default="en", validate=_validate_language)

    # 9. Run time
    answers["run_time"] = _ask("Daily run time (HH:MM in your timezone)", default="07:30", validate=_validate_time)

    # 10. Microsoft tenant id
    tenant = _ask("Microsoft tenant ID (UUID or 'common')", default="common")
    if tenant != "common" and not _looks_like_uuid(tenant):
        print(_yellow("  Warning: that doesn't look like a valid UUID. Proceeding anyway."))
    answers["graph_tenant_id"] = tenant

    # 11. OAuth token (optional)
    if not args.no_prompt_token:
        existing_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
        if existing_token:
            print(_yellow("\n  Warning: CLAUDE_CODE_OAUTH_TOKEN is already set in your environment."))
        try:
            token = getpass.getpass("  Claude Code OAuth token (hidden; leave blank to skip): ")
        except EOFError:
            token = ""
        if token and (token.startswith("sk-") and "replace" in token.lower()):
            print(_red("  Error: token looks like a placeholder. Refusing to write."))
            token = ""
        answers["oauth_token"] = token
    else:
        answers["oauth_token"] = ""

    # 12. ntfy topic
    print("\n  ntfy.sh push notifications (optional). See https://ntfy.sh/ for setup.")
    answers["ntfy_topic"] = _ask("ntfy topic (blank to skip)", default="")

    # 13. healthchecks UUID
    print("  healthchecks.io monitoring (optional). See https://healthchecks.io/ for setup.")
    answers["healthchecks_uuid"] = _ask("healthchecks.io UUID (blank to skip)", default="")

    return answers


def _render_prompt(answers: dict[str, object], repo_root: Path) -> str:
    """Render briefing.md.template with the collected answers."""
    template_path = repo_root / "prompts" / "hyacine.md.template"
    if not template_path.exists():
        # Fallback: look relative to package
        template_path = repo_root / "hyacine.md.template"

    env = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        keep_trailing_newline=True,
    )
    template = env.get_template(template_path.name)

    tz_str = str(answers["timezone"])
    try:
        zinfo = ZoneInfo(tz_str)
        abbr = datetime.now(zinfo).strftime("%Z")
        timezone_display = f"{tz_str} ({abbr})"
    except Exception:
        timezone_display = tz_str

    return template.render(
        name=answers["name"],
        role=answers["role"],
        identity_blurb=answers["identity_blurb"],
        priorities=answers["priorities"],
        categories_md=answers["categories_md"],
        timezone_display=timezone_display,
        email_recipient=answers["email_recipient"],
        language=answers["language"],
    )


def _build_config_yaml(answers: dict[str, object]) -> str:
    """Build config.yaml content from answers."""
    data = {
        "recipient_email": answers["email_recipient"],
        "timezone": answers["timezone"],
        "llm_model": "sonnet",
        "run_time": answers["run_time"],
        "llm_timeout_seconds": 300,
        "fetch_max_emails": 500,
        "initial_watermark_lookback_hours": 24,
        "language": answers["language"],
    }
    return yaml.dump(data, default_flow_style=False, allow_unicode=True)


def _build_env_file(answers: dict[str, object]) -> str:
    """Build hyacine.env content."""
    lines = [
        f"CLAUDE_CODE_OAUTH_TOKEN={answers.get('oauth_token', '')}",
        f"HYACINE_GRAPH_TENANT_ID={answers.get('graph_tenant_id', 'common')}",
        f"HYACINE_NTFY_TOPIC={answers.get('ntfy_topic', '')}",
        f"HYACINE_HEALTHCHECKS_UUID={answers.get('healthchecks_uuid', '')}",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_init(argv: list[str] | None = None) -> int:  # noqa: C901
    """Interactive wizard. Returns 0 on success, non-zero on abort/error."""
    parser = argparse.ArgumentParser(
        prog="hyacine init",
        description="Interactive setup wizard for hyacine.",
    )
    parser.add_argument(
        "--config-dir",
        metavar="PATH",
        help="Override XDG config directory (default: ~/.config/hyacine/)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Back up and overwrite existing files without prompting.",
    )
    parser.add_argument(
        "--no-prompt-token",
        action="store_true",
        help="Skip the OAuth token prompt (useful in CI).",
    )
    args = parser.parse_args(argv)

    # Resolve directories
    if args.config_dir:
        config_dir = Path(args.config_dir).expanduser().resolve()
    else:
        config_dir = _xdg_config_home() / "hyacine"

    state_dir = _xdg_state_home() / "hyacine"

    # Target files
    env_file = config_dir / "hyacine.env"
    config_yaml = config_dir / "config.yaml"
    rules_yaml = config_dir / "rules.yaml"
    prompts_dir = config_dir / "prompts"
    prompt_md = prompts_dir / "hyacine.md"

    print(f"\nTarget config dir : {config_dir}")
    print(f"Target state dir  : {state_dir}")
    print("\nFiles that will be written:")
    for f in [env_file, config_yaml, rules_yaml, prompt_md]:
        print(f"  {f}")

    # Create directories
    config_dir.mkdir(parents=True, exist_ok=True)
    config_dir.chmod(0o700)
    state_dir.mkdir(parents=True, exist_ok=True)
    state_dir.chmod(0o700)
    prompts_dir.mkdir(parents=True, exist_ok=True)

    # Idempotency — check existing files
    skip_all = False
    resolutions: dict[str, str] = {}

    for target in [env_file, config_yaml, rules_yaml, prompt_md]:
        if not target.exists():
            resolutions[str(target)] = RESOLUTION_OVERWRITE  # new file, just write
            continue
        if skip_all:
            resolutions[str(target)] = RESOLUTION_SKIP
            continue
        res = _resolve_existing(target, args.overwrite)
        if res == RESOLUTION_QUIT:
            print("Aborted.")
            return 1
        if res == RESOLUTION_SKIP:
            skip_all = True
        resolutions[str(target)] = res

    # If everything is skipped, nothing to do
    all_skipped = all(v == RESOLUTION_SKIP for v in resolutions.values())
    if all_skipped:
        print(_yellow("\nAll files skipped. Nothing written."))
        return 0

    # Collect answers
    try:
        answers = _collect_answers(args)
    except KeyboardInterrupt:
        print("\n\nAborted.")
        return 1

    # Render content
    repo_root = _repo_root()
    prompt_content = _render_prompt(answers, repo_root)
    config_content = _build_config_yaml(answers)
    env_content = _build_env_file(answers)

    # Write files
    written: list[Path] = []

    def _should_write(path: Path) -> bool:
        return resolutions.get(str(path), RESOLUTION_OVERWRITE) != RESOLUTION_SKIP

    if _should_write(prompt_md):
        prompt_md.write_text(prompt_content, encoding="utf-8")
        written.append(prompt_md)

    if _should_write(config_yaml):
        config_yaml.write_text(config_content, encoding="utf-8")
        written.append(config_yaml)

    if _should_write(rules_yaml):
        # Copy generic starter rules (only if not skipping)
        starter = repo_root / "config" / "rules.starter.yaml"
        if starter.exists():
            shutil.copy2(starter, rules_yaml)
        else:
            rules_yaml.write_text("rules: []\n", encoding="utf-8")
        written.append(rules_yaml)

    if _should_write(env_file):
        env_file.write_text(env_content, encoding="utf-8")
        env_file.chmod(0o600)
        written.append(env_file)

    # Summary
    print("\n" + _green("Setup complete!") + "\n")
    print("Files written:")
    for path in written:
        mode = oct(path.stat().st_mode)[-3:]
        print(f"  {_green('v')} {path}  (mode {mode})")

    print("\nNext steps:")
    print("  1. Complete Microsoft Graph OAuth (one-time):")
    print("       python scripts/bootstrap_auth.py")
    print("  2. Verify the send path:")
    print("       python scripts/test_sendmail.py --yes")
    print("  3. Run your first briefing:")
    print("       python -m hyacine.pipeline.briefing")
    print("  4. Start the web UI:")
    print("       uv run uvicorn hyacine.web.app:app --host 127.0.0.1 --port 8765 --workers 1")

    return 0
