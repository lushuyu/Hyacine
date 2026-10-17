"""Send one test email to verify the Mail.Send scope + /me/sendMail path.

Subject: [TEST] Hyacine sendmail verify
Body:    minimal HTML with timestamp.

Only proceed after explicit interactive confirmation; this script REQUIRES
stdin interaction (press `y` + Enter) before any POST to Graph.

It never signs in. It uses the same silent-only credential as the scheduled
run (auth mode, redirect port and auth record path from Settings) and checks
the cached token before asking to send, so a missing or dead sign-in fails
fast with a pointer to scripts/bootstrap_auth.py.
"""
from __future__ import annotations

import os
import sys
from datetime import UTC, datetime

_GRAPH_SCOPE = "https://graph.microsoft.com/.default"
_BOOTSTRAP_HINT = (
    "run `python scripts/bootstrap_auth.py` to sign in "
    "(it uses HYACINE_GRAPH_AUTH_MODE)"
)


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
        from azure.identity import AuthenticationRequiredError

        from hyacine.config import Settings, load_yaml_config
        from hyacine.graph.auth import load_or_create_record
        from hyacine.graph.send import send_email
    except ImportError as exc:
        print(f"Import error: {exc}", file=sys.stderr)
        return 1

    try:
        settings = Settings()
        yaml_cfg = load_yaml_config(settings.config_path)
        recipient = yaml_cfg.recipient_email
    except Exception as exc:  # noqa: BLE001
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 1

    record_path = settings.auth_record_path
    if not record_path.exists():
        print(f"No Graph sign-in found at {record_path}; {_BOOTSTRAP_HINT}.", file=sys.stderr)
        return 1

    try:
        _cred, _record = load_or_create_record(
            settings.graph_client_id,
            settings.graph_tenant_id,
            settings.auth_dir,
            settings.scope_list,
            auth_mode=settings.graph_auth_mode,
            redirect_port=settings.graph_redirect_port,
            allow_interactive=False,
            record_path=record_path,
        )
        # Fail here, before the confirmation prompt, rather than as a generic
        # sendMail error after the user has said yes.
        _cred.get_token(_GRAPH_SCOPE)
    except AuthenticationRequiredError as exc:
        print(f"Cached Graph token is unusable; {_BOOTSTRAP_HINT}.\n  {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"Graph credential check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
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
    subject = "[TEST] Hyacine sendmail verify"
    body = f"This is an automated Graph sendMail verification sent at {utc_now_iso}."

    try:
        msg_id = send_email(_cred, recipient, subject, body)
    except Exception as exc:  # noqa: BLE001
        print(f"sendMail failed: {exc}", file=sys.stderr)
        return 1

    print(f"Sent OK. Message id: {msg_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
