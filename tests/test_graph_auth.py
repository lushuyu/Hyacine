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
