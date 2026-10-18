"""Tests for the Graph auth scripts: scripts/bootstrap_auth.py and scripts/test_sendmail.py.

No network: credentials and their MSAL apps are mocks. Both scripts import
their hyacine dependencies inside ``main()``, so patching the module
attributes is enough.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock

import pytest
from azure.core.credentials import AccessToken
from azure.identity import AuthenticationRecord, AuthenticationRequiredError

from hyacine.config import Settings
from hyacine.graph.auth import load_authentication_record, save_authentication_record

_SCRIPTS = Path(__file__).parent.parent / "scripts"


def _load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"_hyacine_script_{name}", _SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bootstrap_script = _load_script("bootstrap_auth")
sendmail_script = _load_script("test_sendmail")


def _record(username: str = "alice@example.com") -> AuthenticationRecord:
    return AuthenticationRecord(
        "tenant-id", "client-id", "login.microsoftonline.com", "uid.tid", username
    )


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings with a non-default auth_record_path (HYACINE_AUTH_RECORD_PATH)."""
    fake = Settings.model_construct(
        graph_client_id="client-id",
        graph_tenant_id="tenant-id",
        graph_scopes="User.Read Mail.Send",
        graph_auth_mode="device_code",
        graph_redirect_port=8400,
        auth_dir=tmp_path / "auth",
        auth_record_path=tmp_path / "elsewhere" / "rec.json",
        config_path=tmp_path / "config.yaml",
    )
    monkeypatch.setattr("hyacine.config.Settings", lambda: fake)
    return fake


def _cred(result: dict[str, Any] | None) -> MagicMock:
    """A credential whose MSAL app answers a forced refresh with ``result``."""
    app = MagicMock()
    app.get_accounts.return_value = [{"home_account_id": "uid.tid"}]
    app.acquire_token_silent_with_error.return_value = result
    cred = MagicMock()
    cred._get_app.return_value = app
    # What a plain get_token() would return: a still-valid cached access token.
    cred.get_token.return_value = AccessToken("cached-AT", 1_900_000_000)
    return cred


_REFRESHED = {"access_token": "fresh-AT", "expires_in": 3600}
_REFUSED = {
    "error": "invalid_grant",
    "error_description": "AADSTS530036: the token will never be usable",
}


def _run_bootstrap(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["bootstrap_auth.py", *argv])
    return int(bootstrap_script.main())


def _forced_refresh_calls(cred: MagicMock) -> list[Any]:
    return cred._get_app.return_value.acquire_token_silent_with_error.call_args_list


# ---------------------------------------------------------------------------
# bootstrap_auth.py
# ---------------------------------------------------------------------------

class TestBootstrapStepOne:
    def test_check_redeems_the_refresh_token(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        save_authentication_record(_record(), settings.auth_record_path)
        cred = _cred(_REFRESHED)
        build = MagicMock(return_value=cred)
        monkeypatch.setattr("hyacine.graph.auth.build_credential", build)

        assert _run_bootstrap(monkeypatch, "--check") == 0

        build.assert_called_once()
        assert build.call_args.kwargs["disable_automatic_auth"] is True
        [call] = _forced_refresh_calls(cred)
        assert call.kwargs["force_refresh"] is True
        assert call.args[0] == settings.scope_list
        cred.get_token.assert_not_called()
        out = capsys.readouterr().out
        assert "OK: Graph issued an access token for alice@example.com" in out
        assert "redeeming the cached refresh token" in out

    def test_check_fails_on_a_refused_refresh_token_despite_a_cached_access_token(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        save_authentication_record(_record(), settings.auth_record_path)
        cred = _cred(_REFUSED)
        build = MagicMock(return_value=cred)
        monkeypatch.setattr("hyacine.graph.auth.build_credential", build)

        assert _run_bootstrap(monkeypatch, "--check") == 1

        # The cached access token get_token() would have returned never answers.
        cred.get_token.assert_not_called()
        build.assert_called_once()  # no interactive credential under --check
        captured = capsys.readouterr()
        assert "AADSTS530036" in captured.out
        assert "FAIL" in captured.err
        assert "OK:" not in captured.out

    def test_default_run_signs_in_again_when_the_refresh_token_is_refused(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        save_authentication_record(_record("old@example.com"), settings.auth_record_path)
        silent = _cred(_REFUSED)
        fresh = _cred(_REFRESHED)
        fresh.authenticate.return_value = _record()
        build = MagicMock(side_effect=[silent, fresh])
        monkeypatch.setattr("hyacine.graph.auth.build_credential", build)

        assert _run_bootstrap(monkeypatch) == 0

        first, second = build.call_args_list
        assert first.kwargs["disable_automatic_auth"] is True
        assert second.kwargs["disable_automatic_auth"] is False
        fresh.authenticate.assert_called_once_with(scopes=settings.scope_list)
        # Step 3 proves the new refresh token too, not the access token the
        # sign-in just cached.
        [call] = _forced_refresh_calls(fresh)
        assert call.kwargs["force_refresh"] is True
        fresh.get_token.assert_not_called()
        saved = load_authentication_record(settings.auth_record_path)
        assert saved is not None and saved.username == "alice@example.com"
        assert "OK: Graph issued an access token for alice@example.com" in capsys.readouterr().out

    def test_sign_in_whose_refresh_token_is_refused_reports_failure(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        fresh = _cred(_REFUSED)
        fresh.authenticate.return_value = _record()
        monkeypatch.setattr("hyacine.graph.auth.build_credential", MagicMock(return_value=fresh))

        assert _run_bootstrap(monkeypatch) == 1

        err = capsys.readouterr().err
        assert "token acquisition still failed" in err
        assert "AADSTS530036" in err

    def test_fallback_without_the_private_hook_says_the_refresh_token_was_not_checked(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        save_authentication_record(_record(), settings.auth_record_path)
        cred = MagicMock(spec=["get_token"])
        cred.get_token.return_value = AccessToken("cached-AT", 1_900_000_000)
        monkeypatch.setattr("hyacine.graph.auth.build_credential", MagicMock(return_value=cred))

        assert _run_bootstrap(monkeypatch, "--check") == 0

        cred.get_token.assert_called_once_with(*settings.scope_list)
        captured = capsys.readouterr()
        assert "OK:" in captured.out
        assert "NOTE" in captured.err
        assert "cached access token may have answered" in captured.err

    def test_check_without_a_record_at_the_configured_path_fails(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # A record at the auth_dir default must not count: the configured path wins.
        save_authentication_record(_record(), settings.auth_dir / "auth_record.json")
        build = MagicMock()
        monkeypatch.setattr("hyacine.graph.auth.build_credential", build)

        assert _run_bootstrap(monkeypatch, "--check") == 1

        build.assert_not_called()
        assert f"No auth record at {settings.auth_record_path}" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# test_sendmail.py
# ---------------------------------------------------------------------------

def _no_prompt(*_a: object, **_kw: object) -> str:
    raise AssertionError("must fail before asking for send confirmation")


class TestSendmailAuth:
    @pytest.fixture(autouse=True)
    def _isolate(self, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HYACINE_CONFIRM", raising=False)
        monkeypatch.setattr(
            "hyacine.config.load_yaml_config",
            lambda _path: MagicMock(recipient_email="me@example.com"),
        )
        monkeypatch.setattr("builtins.input", _no_prompt)
        self.send = MagicMock(return_value="msg-id-1")
        monkeypatch.setattr("hyacine.graph.send.send_email", self.send)

    def _run(self, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
        monkeypatch.setattr(sys, "argv", ["test_sendmail.py", *argv])
        return int(sendmail_script.main())

    def test_missing_record_points_at_bootstrap_without_prompting(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        load = MagicMock()
        monkeypatch.setattr("hyacine.graph.auth.load_or_create_record", load)

        assert self._run(monkeypatch) == 1

        load.assert_not_called()
        self.send.assert_not_called()
        err = capsys.readouterr().err
        assert str(settings.auth_record_path) in err
        assert "scripts/bootstrap_auth.py" in err

    def test_dead_token_points_at_bootstrap_before_the_confirmation_prompt(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        save_authentication_record(_record(), settings.auth_record_path)
        cred = MagicMock()
        cred.get_token.side_effect = AuthenticationRequiredError(
            ["https://graph.microsoft.com/.default"], message="AADSTS70043: expired"
        )
        monkeypatch.setattr(
            "hyacine.graph.auth.load_or_create_record",
            MagicMock(return_value=(cred, _record())),
        )

        # Without the early check this would reach the tty guard and return 2.
        assert self._run(monkeypatch) == 1

        self.send.assert_not_called()
        err = capsys.readouterr().err
        assert "unusable" in err
        assert "scripts/bootstrap_auth.py" in err
        assert "AADSTS70043" in err

    def test_uses_the_pipeline_credential_settings(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "graph_auth_mode", "interactive_browser")
        monkeypatch.setattr(settings, "graph_redirect_port", 8411)
        save_authentication_record(_record(), settings.auth_record_path)
        cred = MagicMock()
        load = MagicMock(return_value=(cred, _record()))
        monkeypatch.setattr("hyacine.graph.auth.load_or_create_record", load)

        assert self._run(monkeypatch, "--yes") == 0

        kwargs = load.call_args.kwargs
        assert kwargs["record_path"] == settings.auth_record_path
        assert kwargs["auth_mode"] == "interactive_browser"
        assert kwargs["redirect_port"] == 8411
        assert kwargs["allow_interactive"] is False
        cred.get_token.assert_called_once_with("https://graph.microsoft.com/.default")
        assert self.send.call_args.args[:2] == (cred, "me@example.com")
