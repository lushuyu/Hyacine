"""Interactive Microsoft Graph login (first-time setup, or re-auth after revocation).

    python scripts/bootstrap_auth.py            # sign in if the cache is dead
    python scripts/bootstrap_auth.py --check    # verify only, never prompt
    python scripts/bootstrap_auth.py --reset    # discard cached tokens, force fresh login

The flow used is ``HYACINE_GRAPH_AUTH_MODE`` (``device_code`` or
``interactive_browser``). For ``interactive_browser`` on a headless host,
open a tunnel from the machine that has the browser first:

    ssh -L 8400:localhost:8400 user@host

then run this script over that session. It prints the auth URL; the redirect
comes back through the tunnel to the loopback server on the host.

This script always finishes by acquiring a real token. It reports success
only when Graph actually issued one — a persisted auth_record.json on its own
proves nothing, since loading a record does no network I/O.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path


def _backup_and_remove(path: Path) -> None:
    """Move `path` aside with a timestamp suffix. No-op if absent."""
    if not path.exists():
        return
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = path.with_name(f"{path.name}.bak-{stamp}")
    shutil.move(str(path), str(dest))
    print(f"moved {path} → {dest}")


def _msal_cache_path() -> Path:
    """Where msal-extensions persists the 'hyacine_cache' token cache."""
    return Path.home() / ".IdentityService" / "hyacine_cache.nocae"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the cached token silently; never start an interactive flow",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="back up and discard the cached tokens + auth record before signing in",
    )
    args = parser.parse_args()

    try:
        from azure.identity import AuthenticationRequiredError

        from hyacine.config import Settings
        from hyacine.graph.auth import (
            AUTH_MODE_INTERACTIVE_BROWSER,
            build_credential,
            load_authentication_record,
            save_authentication_record,
            use_console_browser,
        )
    except ImportError as exc:
        print(f"Import error: {exc}", file=sys.stderr)
        return 1

    settings = Settings()
    mode = settings.graph_auth_mode
    record_path = settings.auth_record_path

    print(f"auth mode : {mode}")
    print(f"client id : {settings.graph_client_id}")
    print(f"tenant    : {settings.graph_tenant_id}")
    if mode == AUTH_MODE_INTERACTIVE_BROWSER:
        print(f"redirect  : http://localhost:{settings.graph_redirect_port}")
    print()

    if args.reset:
        if args.check:
            print("--reset and --check are mutually exclusive", file=sys.stderr)
            return 2
        _backup_and_remove(record_path)
        _backup_and_remove(_msal_cache_path())
        print()

    # --- Step 1: try silent refresh against whatever is cached ---
    record = load_authentication_record(record_path)
    if record is not None:
        silent = build_credential(
            settings.graph_client_id,
            settings.graph_tenant_id,
            settings.auth_dir,
            record=record,
            disable_automatic_auth=True,
            auth_mode=mode,
            redirect_port=settings.graph_redirect_port,
        )
        try:
            token = silent.get_token(*settings.scope_list)
        except AuthenticationRequiredError as exc:
            print(f"Cached token unusable — interactive sign-in required.\n  {exc}\n")
        except Exception as exc:  # noqa: BLE001
            print(f"Cached token unusable: {type(exc).__name__}: {exc}\n")
        else:
            _report_ok(record.username, token.expires_on, record_path)
            return 0
    else:
        print(f"No auth record at {record_path}.\n")

    if args.check:
        print("FAIL: no usable cached token (--check does not sign in).", file=sys.stderr)
        return 1

    # --- Step 2: interactive sign-in ---
    if mode == AUTH_MODE_INTERACTIVE_BROWSER:
        use_console_browser()

    cred = build_credential(
        settings.graph_client_id,
        settings.graph_tenant_id,
        settings.auth_dir,
        disable_automatic_auth=False,
        auth_mode=mode,
        redirect_port=settings.graph_redirect_port,
    )

    try:
        new_record = cred.authenticate(scopes=settings.scope_list)
    except Exception as exc:  # noqa: BLE001
        print(f"Authentication failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    save_authentication_record(new_record, record_path)

    # --- Step 3: prove the new credential actually yields a token ---
    try:
        token = cred.get_token(*settings.scope_list)
    except Exception as exc:  # noqa: BLE001
        print(
            f"Signed in as {new_record.username}, but token acquisition still "
            f"failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    _report_ok(new_record.username, token.expires_on, record_path)
    return 0


def _report_ok(username: str, expires_on: int, record_path: Path) -> None:
    import stat

    expiry = datetime.fromtimestamp(expires_on, tz=UTC)
    print(f"OK: Graph issued an access token for {username}")
    print(f"    expires {expiry.isoformat()} ({expires_on})")

    mode = stat.S_IMODE(record_path.stat().st_mode)
    if mode != 0o600:
        print(
            f"WARNING: {record_path} has mode {oct(mode)}, expected 0o600",
            file=sys.stderr,
        )
    print(f"    auth_record.json at {record_path} (mode {oct(mode)})")


if __name__ == "__main__":
    raise SystemExit(main())
