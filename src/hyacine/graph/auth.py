"""Graph credential construction with persistent token cache + AuthenticationRecord.

Two-step lifecycle:
  1. First run  → `build_credential()` opens an interactive flow, user logs in,
     returns AuthenticationRecord that MUST be persisted via
     `save_authentication_record()`.
  2. Subsequent runs → `load_or_create_record()` reads the saved record and
     passes it into the credential so azure-identity picks the right
     account from cache without re-prompting.

Auth modes (``HYACINE_GRAPH_AUTH_MODE``):
  - ``device_code``         — DeviceCodeCredential. Simplest, but many tenants
    now block it via a Conditional Access "authentication flows" policy. The
    symptom is AADSTS530036 on refresh: *"the token will never be usable and
    should be deleted"*. If you see that, switch to ``interactive_browser``.
  - ``interactive_browser`` — InteractiveBrowserCredential (authorization code
    + PKCE). Binds a loopback HTTP server on ``redirect_port`` to catch the
    redirect. On a headless host, run the login over an SSH tunnel:
        ssh -L 8400:localhost:8400 user@host
    and call `use_console_browser()` first so the auth URL is printed instead
    of handed to a browser that does not exist.

Key config notes:
  - TokenCachePersistenceOptions(name="hyacine_cache", allow_unencrypted_storage=True)
    is REQUIRED on headless Linux. Without it, MSAL probes for libsecret/DBus
    and throws "Persistence check failed".
  - Do NOT pip install PyGObject — it enables the encrypted path we're trying
    to skip.
  - Cache file + auth_record.json should be chmod 600.

Unattended callers (the nightly pipeline, the IPC status probes) MUST pass
``allow_interactive=False`` / ``disable_automatic_auth=True``. Without it a
dead refresh token drags the process into an interactive flow that no human
is watching, and it blocks until the flow times out.
"""
from __future__ import annotations

import os
import stat
import sys
import webbrowser
from collections.abc import Callable
from pathlib import Path

from azure.identity import (
    AuthenticationRecord,
    DeviceCodeCredential,
    InteractiveBrowserCredential,
    TokenCachePersistenceOptions,
)

#: Credential types this module can hand back. Both are MSAL public-client
#: credentials sharing one on-disk cache, so a refresh token minted by either
#: flow is usable by the other for silent refresh.
GraphCredential = DeviceCodeCredential | InteractiveBrowserCredential

AUTH_MODE_DEVICE_CODE = "device_code"
AUTH_MODE_INTERACTIVE_BROWSER = "interactive_browser"
_VALID_AUTH_MODES = (AUTH_MODE_DEVICE_CODE, AUTH_MODE_INTERACTIVE_BROWSER)

DEFAULT_REDIRECT_PORT = 8400
DEFAULT_INTERACTIVE_TIMEOUT_SECONDS = 300


def _ensure_auth_dir(auth_dir: Path) -> None:
    """Create auth dir with 700 perms. Callers must still chmod 600 files."""
    auth_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(auth_dir, stat.S_IRWXU)


def _chmod_600(path: Path) -> None:
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


class _ConsoleBrowser(webbrowser.BaseBrowser):
    """A 'browser' that prints the URL and reports success.

    azure-identity's InteractiveBrowserCredential calls ``webbrowser.open()``
    and raises CredentialUnavailableError("Failed to open a browser") when it
    returns False — which is always the case on a headless server. Registering
    this controller makes the URL visible to whoever is running the login so
    they can paste it into a browser on their own machine.
    """

    def open(self, url: str, new: int = 0, autoraise: bool = True) -> bool:  # noqa: ARG002, FBT001, FBT002
        print(
            "\nOpen this URL in a browser on your local machine "
            "(the SSH tunnel carries the redirect back):\n\n"
            f"  {url}\n",
            file=sys.stderr,
            flush=True,
        )
        return True


def use_console_browser() -> None:
    """Route ``webbrowser.open()`` to stderr instead of a real browser.

    Call before triggering an interactive_browser login on a headless host.
    Idempotent.
    """
    webbrowser.register("hyacine-console", None, _ConsoleBrowser(), preferred=True)


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
    prompt_callback: Callable[[str, str, object], None] | None = None,
    auth_mode: str = AUTH_MODE_DEVICE_CODE,
    redirect_port: int = DEFAULT_REDIRECT_PORT,
    interactive_timeout: int = DEFAULT_INTERACTIVE_TIMEOUT_SECONDS,
) -> GraphCredential:
    """Construct a Graph credential with persistent cache + (optional) record.

    When `record` is None, the first get_token() call triggers the interactive
    flow selected by `auth_mode`. When `record` is provided, MSAL selects that
    account silently from cache.

    ``prompt_callback`` is handed straight to MSAL and applies to
    ``device_code`` only. The IPC sidecar passes an emitter here so the
    verification URI + user code reach the webview as a ``graph.device_flow``
    event instead of being printed to stdout (which would corrupt the JSON-RPC
    channel). When unset, falls back to a stdout print so the standalone
    ``bootstrap_auth.py`` CLI still works.

    ``redirect_port`` / ``interactive_timeout`` apply to ``interactive_browser``
    only. The port must be reachable by the browser completing the login —
    over an SSH tunnel when the host is headless.
    """
    if auth_mode not in _VALID_AUTH_MODES:
        raise ValueError(
            f"unknown auth_mode {auth_mode!r}; expected one of {_VALID_AUTH_MODES}"
        )

    _ensure_auth_dir(auth_dir)

    kwargs: dict = dict(
        client_id=client_id,
        tenant_id=tenant_id,
        cache_persistence_options=TokenCachePersistenceOptions(
            name="hyacine_cache",
            allow_unencrypted_storage=True,
        ),
        disable_automatic_authentication=disable_automatic_auth,
    )
    if record is not None:
        kwargs["authentication_record"] = record

    if auth_mode == AUTH_MODE_INTERACTIVE_BROWSER:
        return InteractiveBrowserCredential(
            redirect_uri=f"http://localhost:{redirect_port}",
            timeout=interactive_timeout,
            **kwargs,
        )

    def _default_prompt(verification_uri: str, user_code: str, expires_on: object) -> None:
        print(f"To sign in, visit {verification_uri} and enter code {user_code}", flush=True)

    return DeviceCodeCredential(
        prompt_callback=prompt_callback or _default_prompt,
        **kwargs,
    )


def load_or_create_record(
    client_id: str,
    tenant_id: str,
    auth_dir: Path,
    scopes: list[str],
    *,
    auth_mode: str = AUTH_MODE_DEVICE_CODE,
    redirect_port: int = DEFAULT_REDIRECT_PORT,
    allow_interactive: bool = True,
) -> tuple[GraphCredential, AuthenticationRecord]:
    """High-level helper: if record exists, load it; else run the interactive flow.

    Returns a credential already wired to the cached/created record.

    NOTE: when a record already exists this does **no** network I/O — it
    deserializes the record and returns. A returned credential therefore
    proves nothing about whether the cached refresh token still works; only a
    subsequent ``get_token()`` does. Callers that want to *verify* sign-in
    must call ``get_token()`` and handle the failure.

    ``allow_interactive=False`` makes the returned credential silent-only: a
    cache miss or a revoked refresh token raises AuthenticationRequiredError
    immediately instead of starting a flow nobody is present to complete.
    Unattended callers must set it.
    """
    record_path = auth_dir / "auth_record.json"
    existing = load_authentication_record(record_path)

    if existing is not None:
        cred = build_credential(
            client_id,
            tenant_id,
            auth_dir,
            record=existing,
            disable_automatic_auth=not allow_interactive,
            auth_mode=auth_mode,
            redirect_port=redirect_port,
        )
        return cred, existing

    if not allow_interactive:
        raise RuntimeError(
            f"no AuthenticationRecord at {record_path} and interactive auth is "
            "disabled; run scripts/bootstrap_auth.py to sign in"
        )

    cred = build_credential(
        client_id,
        tenant_id,
        auth_dir,
        disable_automatic_auth=False,
        auth_mode=auth_mode,
        redirect_port=redirect_port,
    )
    record = cred.authenticate(scopes=scopes)
    save_authentication_record(record, record_path)
    return cred, record


__all__ = [
    "AUTH_MODE_DEVICE_CODE",
    "AUTH_MODE_INTERACTIVE_BROWSER",
    "DEFAULT_REDIRECT_PORT",
    "GraphCredential",
    "build_credential",
    "load_authentication_record",
    "save_authentication_record",
    "load_or_create_record",
    "use_console_browser",
    "AuthenticationRecord",
    "DeviceCodeCredential",
    "InteractiveBrowserCredential",
    "TokenCachePersistenceOptions",
    "_chmod_600",
]
