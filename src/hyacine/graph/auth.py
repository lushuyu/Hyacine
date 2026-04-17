"""DeviceCodeCredential with persistent token cache + AuthenticationRecord.

Two-step lifecycle:
  1. First run  → `build_credential()` opens device code flow, user logs in,
     returns AuthenticationRecord that MUST be persisted via
     `save_authentication_record()`.
  2. Subsequent runs → `load_or_create_record()` reads the saved record and
     passes it into DeviceCodeCredential so azure-identity picks the right
     account from cache without re-prompting.

Key config notes (see task brief §1):
  - TokenCachePersistenceOptions(name="hyacine_cache", allow_unencrypted_storage=True)
    is REQUIRED on headless Linux. Without it, MSAL probes for libsecret/DBus
    and throws "Persistence check failed".
  - Do NOT pip install PyGObject — it enables the encrypted path we're trying
    to skip.
  - Cache file + auth_record.json should be chmod 600.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

from azure.identity import AuthenticationRecord, DeviceCodeCredential, TokenCachePersistenceOptions


def _ensure_auth_dir(auth_dir: Path) -> None:
    """Create auth dir with 700 perms. Callers must still chmod 600 files."""
    auth_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(auth_dir, stat.S_IRWXU)


def _chmod_600(path: Path) -> None:
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def load_authentication_record(record_path: Path) -> AuthenticationRecord | None:
    """Return the cached AuthenticationRecord, or None if first run."""
    if not record_path.exists():
        return None
    text = record_path.read_text(encoding="utf-8")
    return AuthenticationRecord.deserialize(text)


def save_authentication_record(record: AuthenticationRecord, record_path: Path) -> None:
    """Serialize record to disk and chmod 600. Must be called after first login."""
    _ensure_auth_dir(record_path.parent)
    record_path.write_text(record.serialize(), encoding="utf-8")
    _chmod_600(record_path)


def build_credential(
    client_id: str,
    tenant_id: str,
    auth_dir: Path,
    *,
    record: AuthenticationRecord | None = None,
    disable_automatic_auth: bool = False,
) -> DeviceCodeCredential:
    """Construct DeviceCodeCredential with persistent cache + (optional) record.

    When `record` is None, the first get_token() call triggers device code flow.
    When `record` is provided, MSAL selects that account silently from cache.
    """
    _ensure_auth_dir(auth_dir)

    def _prompt_callback(verification_uri: str, user_code: str, expires_on: object) -> None:
        print(f"To sign in, visit {verification_uri} and enter code {user_code}", flush=True)

    kwargs: dict = dict(
        client_id=client_id,
        tenant_id=tenant_id,
        cache_persistence_options=TokenCachePersistenceOptions(
            name="hyacine_cache",
            allow_unencrypted_storage=True,
        ),
        prompt_callback=_prompt_callback,
        disable_automatic_authentication=disable_automatic_auth,
    )
    if record is not None:
        kwargs["authentication_record"] = record

    return DeviceCodeCredential(**kwargs)


def load_or_create_record(
    client_id: str,
    tenant_id: str,
    auth_dir: Path,
    scopes: list[str],
) -> tuple[DeviceCodeCredential, AuthenticationRecord]:
    """High-level helper: if record exists, load it; else run device code and save.

    Returns a credential already wired to the cached/created record.
    """
    record_path = auth_dir / "auth_record.json"
    existing = load_authentication_record(record_path)

    if existing is not None:
        cred = build_credential(client_id, tenant_id, auth_dir, record=existing)
        return cred, existing

    cred = build_credential(client_id, tenant_id, auth_dir, disable_automatic_auth=False)
    record = cred.authenticate(scopes=scopes)
    save_authentication_record(record, record_path)
    return cred, record


__all__ = [
    "build_credential",
    "load_authentication_record",
    "save_authentication_record",
    "load_or_create_record",
    "AuthenticationRecord",
    "DeviceCodeCredential",
    "TokenCachePersistenceOptions",
    "_chmod_600",
]
