"""Tests for hyacine.graph.auth — no network, no real credentials."""
from __future__ import annotations

import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# test_build_credential_wires_persistence_options
# ---------------------------------------------------------------------------

def test_build_credential_wires_persistence_options(tmp_path: Path) -> None:
    """DeviceCodeCredential must be built with the unencrypted persistence opts."""
    captured: dict = {}

    def fake_dcc(**kwargs: object) -> MagicMock:
        captured.update(kwargs)
        return MagicMock()

    with patch("hyacine.graph.auth.DeviceCodeCredential", side_effect=fake_dcc):
        from hyacine.graph.auth import build_credential

        build_credential("client-id", "tenant-id", tmp_path)

    opts = captured.get("cache_persistence_options")
    assert opts is not None, "cache_persistence_options must be passed"
    assert opts.allow_unencrypted_storage is True
    assert opts.name == "hyacine_cache"


# ---------------------------------------------------------------------------
# test_save_and_load_record_round_trip
# ---------------------------------------------------------------------------

def test_save_and_load_record_round_trip(tmp_path: Path) -> None:
    """save_authentication_record writes JSON; load_authentication_record reads it back."""
    from hyacine.graph.auth import load_authentication_record, save_authentication_record

    record_path = tmp_path / "auth_record.json"
    fake_json = '{"username": "test@example.com", "homeAccountId": "abc"}'

    # Build a fake record whose serialize() returns our JSON
    fake_record = MagicMock()
    fake_record.serialize.return_value = fake_json

    # Patch AuthenticationRecord.deserialize to return a known object
    expected = MagicMock()
    with patch("hyacine.graph.auth.AuthenticationRecord") as mock_ar:
        mock_ar.deserialize.return_value = expected
        save_authentication_record(fake_record, record_path)

        assert record_path.exists(), "record file should be written"
        assert record_path.read_text() == fake_json

        # Check chmod 600
        mode = stat.S_IMODE(record_path.stat().st_mode)
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"

        loaded = load_authentication_record(record_path)

    mock_ar.deserialize.assert_called_once_with(fake_json)
    assert loaded is expected


# ---------------------------------------------------------------------------
# test_load_returns_none_when_missing
# ---------------------------------------------------------------------------

def test_load_returns_none_when_missing(tmp_path: Path) -> None:
    """load_authentication_record returns None when the file does not exist."""
    from hyacine.graph.auth import load_authentication_record

    result = load_authentication_record(tmp_path / "nonexistent.json")
    assert result is None


# ---------------------------------------------------------------------------
# auth modes + unattended (silent-only) credentials
# ---------------------------------------------------------------------------

def test_interactive_browser_mode_uses_loopback_redirect(tmp_path: Path) -> None:
    captured: dict = {}

    def fake_ibc(**kwargs: object) -> MagicMock:
        captured.update(kwargs)
        return MagicMock()

    with patch("hyacine.graph.auth.InteractiveBrowserCredential", side_effect=fake_ibc):
        from hyacine.graph.auth import AUTH_MODE_INTERACTIVE_BROWSER, build_credential

        build_credential(
            "client-id", "tenant-id", tmp_path,
            auth_mode=AUTH_MODE_INTERACTIVE_BROWSER, redirect_port=8411,
        )

    assert captured["redirect_uri"] == "http://localhost:8411"
    assert captured["cache_persistence_options"].allow_unencrypted_storage is True
    # prompt_callback is a device-code-only kwarg.
    assert "prompt_callback" not in captured


def test_unknown_auth_mode_is_rejected(tmp_path: Path) -> None:
    import pytest

    from hyacine.graph.auth import build_credential

    with pytest.raises(ValueError, match="unknown auth_mode"):
        build_credential("client-id", "tenant-id", tmp_path, auth_mode="magic")


def test_silent_only_without_record_raises_instead_of_prompting(tmp_path: Path) -> None:
    import pytest

    from hyacine.graph.auth import load_or_create_record

    with patch("hyacine.graph.auth.DeviceCodeCredential") as dcc:
        with pytest.raises(RuntimeError, match="bootstrap_auth.py"):
            load_or_create_record(
                "client-id", "tenant-id", tmp_path, ["User.Read"], allow_interactive=False
            )
    dcc.assert_not_called()


def test_silent_only_with_record_disables_automatic_auth(tmp_path: Path) -> None:
    captured: dict = {}

    def fake_dcc(**kwargs: object) -> MagicMock:
        captured.update(kwargs)
        return MagicMock()

    record = MagicMock()
    with (
        patch("hyacine.graph.auth.load_authentication_record", return_value=record),
        patch("hyacine.graph.auth.DeviceCodeCredential", side_effect=fake_dcc),
    ):
        from hyacine.graph.auth import load_or_create_record

        _, returned = load_or_create_record(
            "client-id", "tenant-id", tmp_path, ["User.Read"], allow_interactive=False
        )

    assert returned is record
    assert captured["authentication_record"] is record
    assert captured["disable_automatic_authentication"] is True


# ---------------------------------------------------------------------------
# record_path override (HYACINE_AUTH_RECORD_PATH)
# ---------------------------------------------------------------------------

def test_record_path_overrides_the_auth_dir_default(tmp_path: Path) -> None:
    custom = tmp_path / "elsewhere" / "rec.json"
    record = MagicMock()
    with (
        patch("hyacine.graph.auth.load_authentication_record", return_value=record) as load,
        patch("hyacine.graph.auth.DeviceCodeCredential"),
    ):
        from hyacine.graph.auth import load_or_create_record

        _, returned = load_or_create_record(
            "client-id", "tenant-id", tmp_path / "auth", ["User.Read"],
            allow_interactive=False, record_path=custom,
        )

    load.assert_called_once_with(custom)
    assert returned is record


def test_record_path_defaults_to_auth_dir(tmp_path: Path) -> None:
    with (
        patch("hyacine.graph.auth.load_authentication_record", return_value=MagicMock()) as load,
        patch("hyacine.graph.auth.DeviceCodeCredential"),
    ):
        from hyacine.graph.auth import load_or_create_record

        load_or_create_record(
            "client-id", "tenant-id", tmp_path, ["User.Read"], allow_interactive=False
        )

    load.assert_called_once_with(tmp_path / "auth_record.json")


def test_missing_record_error_names_the_overridden_path(tmp_path: Path) -> None:
    import pytest

    from hyacine.graph.auth import load_or_create_record

    custom = tmp_path / "elsewhere" / "rec.json"
    with pytest.raises(RuntimeError, match="rec.json"):
        load_or_create_record(
            "client-id", "tenant-id", tmp_path, ["User.Read"],
            allow_interactive=False, record_path=custom,
        )


def test_interactive_sign_in_saves_to_the_overridden_path(tmp_path: Path) -> None:
    custom = tmp_path / "elsewhere" / "rec.json"
    new_record = MagicMock()
    cred = MagicMock()
    cred.authenticate.return_value = new_record
    with (
        patch("hyacine.graph.auth.DeviceCodeCredential", return_value=cred),
        patch("hyacine.graph.auth.save_authentication_record") as save,
    ):
        from hyacine.graph.auth import load_or_create_record

        load_or_create_record(
            "client-id", "tenant-id", tmp_path, ["User.Read"], record_path=custom
        )

    save.assert_called_once_with(new_record, custom)


# ---------------------------------------------------------------------------
# redeem_refresh_token: prove the refresh token, not a cached access token
# ---------------------------------------------------------------------------

def _fake_record() -> MagicMock:
    record = MagicMock()
    record.username = "alice@example.com"
    record.home_account_id = "uid.tid"
    return record


def _cred_with_app(app: MagicMock) -> MagicMock:
    cred = MagicMock()
    cred._get_app.return_value = app
    return cred


def test_redeem_forces_a_refresh_for_the_record_account() -> None:
    import time

    from hyacine.graph.auth import redeem_refresh_token

    ours = {"home_account_id": "uid.tid", "username": "alice@example.com"}
    app = MagicMock()
    app.get_accounts.return_value = [{"home_account_id": "someone.else"}, ours]
    app.acquire_token_silent_with_error.return_value = {
        "access_token": "AT", "expires_in": 3600,
    }
    cred = _cred_with_app(app)

    before = int(time.time())
    check = redeem_refresh_token(cred, _fake_record(), ["User.Read", "Mail.Send"])

    app.get_accounts.assert_called_once_with(username="alice@example.com")
    app.acquire_token_silent_with_error.assert_called_once_with(
        ["User.Read", "Mail.Send"], account=ours, force_refresh=True
    )
    assert check.refresh_token_redeemed is True
    assert before + 3600 <= check.expires_on <= int(time.time()) + 3600
    # A cached access token must not be allowed to answer for the refresh token.
    cred.get_token.assert_not_called()


def test_redeem_raises_when_entra_refuses_the_refresh_token() -> None:
    import pytest
    from azure.identity import AuthenticationRequiredError

    from hyacine.graph.auth import redeem_refresh_token

    app = MagicMock()
    app.get_accounts.return_value = [{"home_account_id": "uid.tid"}]
    app.acquire_token_silent_with_error.return_value = {
        "error": "invalid_grant",
        "error_description": "AADSTS530036: the token will never be usable",
    }
    cred = _cred_with_app(app)

    with pytest.raises(AuthenticationRequiredError, match="AADSTS530036"):
        redeem_refresh_token(cred, _fake_record(), ["User.Read"])
    cred.get_token.assert_not_called()


def test_redeem_raises_when_the_cache_has_no_matching_account() -> None:
    import pytest
    from azure.identity import AuthenticationRequiredError

    from hyacine.graph.auth import redeem_refresh_token

    app = MagicMock()
    app.get_accounts.return_value = [{"home_account_id": "someone.else"}]
    cred = _cred_with_app(app)

    with pytest.raises(AuthenticationRequiredError, match="no cached refresh token"):
        redeem_refresh_token(cred, _fake_record(), ["User.Read"])
    app.acquire_token_silent_with_error.assert_not_called()
    cred.get_token.assert_not_called()


def test_redeem_falls_back_to_get_token_without_the_private_hook() -> None:
    from hyacine.graph.auth import redeem_refresh_token

    cred = MagicMock(spec=["get_token"])  # no _get_app
    cred.get_token.return_value = MagicMock(expires_on=1_900_000_000)

    check = redeem_refresh_token(cred, _fake_record(), ["User.Read", "Mail.Send"])

    cred.get_token.assert_called_once_with("User.Read", "Mail.Send")
    assert check.expires_on == 1_900_000_000
    assert check.refresh_token_redeemed is False


def test_redeem_falls_back_when_the_private_hook_changed_signature() -> None:
    from hyacine.graph.auth import redeem_refresh_token

    cred = MagicMock()
    cred._get_app.side_effect = TypeError("_get_app() missing 1 required argument")
    cred.get_token.return_value = MagicMock(expires_on=1_900_000_000)

    check = redeem_refresh_token(cred, _fake_record(), ["User.Read"])

    assert check.refresh_token_redeemed is False
    cred.get_token.assert_called_once_with("User.Read")


def test_redeem_falls_back_when_msal_rejects_force_refresh() -> None:
    from hyacine.graph.auth import redeem_refresh_token

    app = MagicMock()
    app.get_accounts.return_value = [{"home_account_id": "uid.tid"}]
    app.acquire_token_silent_with_error.side_effect = TypeError(
        "unexpected keyword argument 'force_refresh'"
    )
    cred = _cred_with_app(app)
    cred.get_token.return_value = MagicMock(expires_on=1_900_000_000)

    check = redeem_refresh_token(cred, _fake_record(), ["User.Read"])

    assert check.refresh_token_redeemed is False
    cred.get_token.assert_called_once_with("User.Read")


def test_redeem_reaches_the_hook_on_the_installed_azure_identity(tmp_path: Path) -> None:
    """The private hook exists on both credential classes build_credential returns.

    Guards against the fallback silently becoming the only path after an
    azure-identity / MSAL upgrade: if this fails, re-check ``_get_app()``.
    """
    import inspect

    import msal
    from azure.identity import AuthenticationRecord

    from hyacine.graph.auth import (
        AUTH_MODE_DEVICE_CODE,
        AUTH_MODE_INTERACTIVE_BROWSER,
        build_credential,
        redeem_refresh_token,
    )

    record = AuthenticationRecord(
        "tenant-id", "client-id", "login.microsoftonline.com", "uid.tid", "alice@example.com"
    )
    app = MagicMock()
    app.get_accounts.return_value = [{"home_account_id": "uid.tid"}]
    app.acquire_token_silent_with_error.return_value = {"access_token": "AT", "expires_in": 60}

    for mode in (AUTH_MODE_DEVICE_CODE, AUTH_MODE_INTERACTIVE_BROWSER):
        cred = build_credential(
            "client-id", "tenant-id", tmp_path, record=record,
            disable_automatic_auth=True, auth_mode=mode,
        )
        assert callable(getattr(cred, "_get_app", None)), mode
        params = inspect.signature(type(cred)._get_app).parameters.values()
        assert all(
            p.kind is p.VAR_KEYWORD or p.default is not p.empty
            for p in params
            if p.name != "self"
        ), mode
        with patch.object(type(cred), "_get_app", return_value=app) as get_app:
            check = redeem_refresh_token(cred, record, ["User.Read"])
        get_app.assert_called_once_with()
        assert check.refresh_token_redeemed is True, mode

    silent = inspect.signature(msal.PublicClientApplication.acquire_token_silent_with_error)
    assert "force_refresh" in silent.parameters
