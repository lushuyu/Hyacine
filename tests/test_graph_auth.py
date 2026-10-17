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
