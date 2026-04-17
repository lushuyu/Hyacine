"""Interactive first-time Microsoft Graph login.

Run once:
    python scripts/bootstrap_auth.py

Prints a URL + 8-char device code. Open the URL in any browser, sign in with
your Microsoft account, and complete any MFA required. After success this
script persists ``auth_record.json`` (chmod 600) in the configured auth_dir
(default ``./data/auth/``) so future runs authenticate silently.
"""
from __future__ import annotations

import sys


def main() -> int:
    try:
        from hyacine.config import Settings
        from hyacine.graph.auth import load_or_create_record
    except ImportError as exc:
        print(f"Import error: {exc}", file=sys.stderr)
        return 1

    try:
        settings = Settings()
        cred, record = load_or_create_record(
            settings.graph_client_id,
            settings.graph_tenant_id,
            settings.auth_dir,
            settings.scope_list,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Authentication failed: {exc}", file=sys.stderr)
        return 1

    print(f"Authorized as {record.username}")

    record_path = settings.auth_record_path
    if not record_path.exists():
        print(f"ERROR: auth_record.json not found at {record_path}", file=sys.stderr)
        return 1

    import stat

    mode = stat.S_IMODE(record_path.stat().st_mode)
    if mode != 0o600:
        print(
            f"WARNING: {record_path} has mode {oct(mode)}, expected 0o600",
            file=sys.stderr,
        )

    print(f"auth_record.json present at {record_path} (mode {oct(mode)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
