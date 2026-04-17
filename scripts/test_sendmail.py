"""Send one test email to verify the Mail.Send scope + /me/sendMail path.

Subject: [TEST] Briefing sendmail verify
Body:    minimal HTML with timestamp.

Only proceed after explicit interactive confirmation; this script REQUIRES
stdin interaction (press `y` + Enter) before any POST to Graph.
"""
from __future__ import annotations

import os
import sys
from datetime import UTC, datetime


def _is_preconfirmed(argv: list[str]) -> bool:
    """CLI flag or env var skips the interactive prompt.

    Why: systemd-style callers have no tty and need a non-interactive path,
    but we don't want `echo y | script` to trivially bypass the guard.
    """
    if "--yes" in argv or "-y" in argv:
        return True
    return os.environ.get("HYACINE_CONFIRM") == "1"


def main() -> int:
    try:
        from hyacine.config import Settings, load_yaml_config
        from hyacine.graph.auth import load_or_create_record
        from hyacine.graph.send import send_briefing_email
    except ImportError as exc:
        print(f"Import error: {exc}", file=sys.stderr)
        return 1

    try:
        settings = Settings()
        yaml_cfg = load_yaml_config(settings.config_path)
        recipient = yaml_cfg.recipient_email

        _cred, _record = load_or_create_record(
            settings.graph_client_id,
            settings.graph_tenant_id,
            settings.auth_dir,
            settings.scope_list,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 1

    print(f"Target recipient: {recipient}")

    if _is_preconfirmed(sys.argv[1:]):
        print("Pre-confirmed via --yes / HYACINE_CONFIRM=1; sending without prompt.")
    elif not sys.stdin.isatty():
        print("stdin is not a tty — aborting (use --yes to bypass)", file=sys.stderr)
        return 2
    else:
        try:
            answer = input(f"Send [TEST] sendmail verify to {recipient}? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            return 2
        if answer != "y":
            print("Aborted.", file=sys.stderr)
            return 2

    utc_now_iso = datetime.now(tz=UTC).isoformat()
    subject = "[TEST] Briefing sendmail verify"
    body = f"This is an automated Graph sendMail verification sent at {utc_now_iso}."

    try:
        msg_id = send_briefing_email(_cred, recipient, subject, body)
    except Exception as exc:  # noqa: BLE001
        print(f"sendMail failed: {exc}", file=sys.stderr)
        return 1

    print(f"Sent OK. Message id: {msg_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
