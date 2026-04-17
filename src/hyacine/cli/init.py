"""Interactive setup wizard for hyacine.

Entry point: ``python -m hyacine init [--overwrite] [--no-prompt-token]``

Flow:
  1. Resolve in-repo config / prompt / data dirs.
  2. Ensure directories exist.
  3. Idempotency check on each target file (update / backup+overwrite / skip).
  4. Collect answers from the user.
  5. Render prompts/hyacine.md from Jinja2 template.
  6. Write config.yaml, rules.yaml, and .env (update mode merges .env:
     blank answers keep existing values, unknown keys are preserved).
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
    return Path(__file__).parent.parent.parent.parent


# ---------------------------------------------------------------------------
# File idempotency resolution
# ---------------------------------------------------------------------------

RESOLUTION_SKIP = "skip"
RESOLUTION_UPDATE = "update"
RESOLUTION_OVERWRITE = "overwrite"
RESOLUTION_QUIT = "quit"


def _resolve_existing(path: Path, overwrite: bool) -> str:
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
    print("\n" + "=" * 60)
    print("  hyacine setup wizard")
    print("  Press Ctrl-C to abort at any time.")
    print("=" * 60 + "\n")

    answers: dict[str, object] = {}

    answers["name"] = _ask("Your display name (e.g. Alice)")
    answers["role"] = _ask("Your role (e.g. PM at Acme Robotics)")

    print()
    answers["identity_blurb"] = _ask_multiline(
        "Identity blurb — 1-3 sentences about yourself, focus areas, research interests"
    )

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

    answers["email_recipient"] = _ask("Email recipient (where the daily report is sent)")
    answers["timezone"] = _ask("Timezone (IANA, e.g. America/New_York)", default="UTC", validate=_validate_tz)
    answers["language"] = _ask("Language (en / zh-CN)", default="en", validate=_validate_language)
    answers["run_time"] = _ask("Daily run time (HH:MM in your timezone)", default="07:30", validate=_validate_time)

    tenant = _ask("Microsoft tenant ID (UUID or 'common')", default="common")
    if tenant != "common" and not _looks_like_uuid(tenant):
        print(_yellow("  Warning: that doesn't look like a valid UUID. Proceeding anyway."))
    answers["graph_tenant_id"] = tenant

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

    print("\n  ntfy.sh push notifications (optional). See https://ntfy.sh/ for setup.")
    answers["ntfy_topic"] = _ask("ntfy topic (blank to skip)", default="")

    print("  healthchecks.io monitoring (optional). See https://healthchecks.io/ for setup.")
    answers["healthchecks_uuid"] = _ask("healthchecks.io UUID (blank to skip)", default="")

    return answers


def _render_prompt(answers: dict[str, object], repo_root: Path) -> str:
    template_path = repo_root / "prompts" / "hyacine.md.template"
    if not template_path.exists():
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


_MANAGED_ENV_KEYS = (
    "CLAUDE_CODE_OAUTH_TOKEN",
    "HYACINE_GRAPH_TENANT_ID",
    "HYACINE_NTFY_TOPIC",
    "HYACINE_HEALTHCHECKS_UUID",
)


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a dotenv file with the same grammar pydantic-settings uses.

    Delegates to python-dotenv (a transitive dep via pydantic-settings), so
    `export KEY=val`, quoted values, inline `# comment` tails, and escape
    sequences are handled identically to how the runtime loader reads the
    file — guaranteeing merge mode doesn't misparse existing entries.
    """
    if not path.exists():
        return {}
    from dotenv import dotenv_values  # noqa: PLC0415

    return {k: v for k, v in dotenv_values(path).items() if v is not None}


def _build_env_file(
    answers: dict[str, object],
    existing: dict[str, str] | None = None,
) -> str:
    # In update mode, blank wizard answers keep whatever was already in .env,
    # and any keys the wizard doesn't manage are preserved at the end.
    values: dict[str, str] = {
        "CLAUDE_CODE_OAUTH_TOKEN": str(answers.get("oauth_token", "")),
        "HYACINE_GRAPH_TENANT_ID": str(answers.get("graph_tenant_id", "common")),
        "HYACINE_NTFY_TOPIC": str(answers.get("ntfy_topic", "")),
        "HYACINE_HEALTHCHECKS_UUID": str(answers.get("healthchecks_uuid", "")),
    }
    if existing:
        for key in _MANAGED_ENV_KEYS:
            if not values[key] and existing.get(key):
                values[key] = existing[key]

    lines = [f"{k}={values[k]}" for k in _MANAGED_ENV_KEYS]
    if existing:
        for key, val in existing.items():
            if key not in _MANAGED_ENV_KEYS:
                lines.append(f"{key}={val}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_init(argv: list[str] | None = None) -> int:  # noqa: C901
    parser = argparse.ArgumentParser(
        prog="hyacine init",
        description="Interactive setup wizard for hyacine.",
    )
    parser.add_argument(
        "--repo-root",
        metavar="PATH",
        help="Override the repo root (default: auto-detected).",
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

    repo_root = Path(args.repo_root).expanduser().resolve() if args.repo_root else _repo_root()

    config_dir = repo_root / "config"
    prompts_dir = repo_root / "prompts"
    data_dir = repo_root / "data"

    env_file = repo_root / ".env"
    config_yaml = config_dir / "config.yaml"
    rules_yaml = config_dir / "rules.yaml"
    prompt_md = prompts_dir / "hyacine.md"

    print(f"\nRepo root  : {repo_root}")
    print("Files that will be written:")
    for f in [env_file, config_yaml, rules_yaml, prompt_md]:
        print(f"  {f}")

    config_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    # Tighten directory perms: data/ holds the DB with run history and
    # generated markdown; prompts/ and config/ hold personal identity +
    # operational settings. 0700 means only the owner can traverse.
    for directory in (config_dir, prompts_dir, data_dir):
        try:
            directory.chmod(0o700)
        except OSError:
            pass

    skip_all = False
    resolutions: dict[str, str] = {}

    for target in [env_file, config_yaml, rules_yaml, prompt_md]:
        if not target.exists():
            resolutions[str(target)] = RESOLUTION_OVERWRITE
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

    all_skipped = all(v == RESOLUTION_SKIP for v in resolutions.values())
    if all_skipped:
        print(_yellow("\nAll files skipped. Nothing written."))
        return 0

    try:
        answers = _collect_answers(args)
    except KeyboardInterrupt:
        print("\n\nAborted.")
        return 1

    prompt_content = _render_prompt(answers, repo_root)
    config_content = _build_config_yaml(answers)

    existing_env = (
        _parse_env_file(env_file)
        if resolutions.get(str(env_file)) == RESOLUTION_UPDATE
        else None
    )
    env_content = _build_env_file(answers, existing=existing_env)

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
    print("  3. Run your first hyacine report:")
    print("       python -m hyacine run")
    print("  4. Start the web UI:")
    print("       uv run uvicorn hyacine.web.app:app --host 127.0.0.1 --port 8765 --workers 1")

    return 0
