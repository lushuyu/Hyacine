"""Tests for the CLI entry ``hyacine.pipeline.run.main`` — exit codes, output,
the best-effort ntfy failure alert, the SIGTERM handler, and the helpers that
decide whether a failed send may be retried. ``run_pipeline`` is always stubbed.
"""
from __future__ import annotations

import signal
import sqlite3
import traceback
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from hyacine.graph._http import GraphHTTPError
from hyacine.models import RunRecord, RunStatus
from hyacine.pipeline import run as run_module

_TB = (
    "Traceback (most recent call last):\n"
    '  File "run.py", line 346, in run_pipeline\n'
    "    sent_message_id = send_email(\n"
    "RuntimeError: SMTP error\n"
)


def _record(status: RunStatus, **kwargs: Any) -> RunRecord:
    now = datetime(2024, 6, 15, 2, 0, tzinfo=UTC)
    return RunRecord(
        id=7,
        started_at=now,
        status=status,
        window_from=now,
        window_to=now,
        **kwargs,
    )


@pytest.fixture
def ntfy_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture send_ntfy calls and point settings at a non-empty topic."""
    from hyacine.config import Settings

    monkeypatch.setattr(
        run_module,
        "_get_settings",
        lambda: Settings.model_construct(ntfy_topic="secret-topic"),
    )
    calls: list[dict[str, Any]] = []

    def fake_send_ntfy(topic: str, message: str, **kwargs: Any) -> bool:
        calls.append({"topic": topic, "message": message, **kwargs})
        return True

    monkeypatch.setattr("hyacine.ops.monitoring.send_ntfy", fake_send_ntfy)
    return calls


def _stub_pipeline(monkeypatch: pytest.MonkeyPatch, result: RunRecord | Exception) -> None:
    def fake_run_pipeline(*args: Any, **kwargs: Any) -> RunRecord:
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(run_module, "run_pipeline", fake_run_pipeline)


class TestMainSuccess:
    def test_success_returns_zero_and_sends_no_alert(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        ntfy_calls: list[dict[str, Any]],
    ) -> None:
        _stub_pipeline(
            monkeypatch,
            _record(RunStatus.SUCCESS, sent_message_id="msg-1", email_count=3),
        )

        assert run_module.main() == 0
        assert capsys.readouterr().out.strip() == "OK: sent=msg-1 emails=3"
        assert ntfy_calls == []


class TestMainFailedRecord:
    def test_failed_record_alerts_with_last_traceback_line(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        ntfy_calls: list[dict[str, Any]],
    ) -> None:
        _stub_pipeline(monkeypatch, _record(RunStatus.FAILED, error_traceback=_TB))

        assert run_module.main() == 1
        assert capsys.readouterr().out.strip() == "FAIL: RuntimeError: SMTP error"
        assert len(ntfy_calls) == 1
        assert ntfy_calls[0]["topic"] == "secret-topic"
        assert ntfy_calls[0]["message"] == "run 7 failed: RuntimeError: SMTP error"

    def test_alert_never_carries_the_full_traceback(
        self,
        monkeypatch: pytest.MonkeyPatch,
        ntfy_calls: list[dict[str, Any]],
    ) -> None:
        _stub_pipeline(monkeypatch, _record(RunStatus.FAILED, error_traceback=_TB))

        run_module.main()

        message = ntfy_calls[0]["message"]
        assert "Traceback" not in message
        assert "send_email(" not in message

    def test_failed_record_without_traceback_still_alerts(
        self,
        monkeypatch: pytest.MonkeyPatch,
        ntfy_calls: list[dict[str, Any]],
    ) -> None:
        _stub_pipeline(monkeypatch, _record(RunStatus.FAILED))

        assert run_module.main() == 1
        assert ntfy_calls[0]["message"] == "run 7 failed: PipelineError"


class TestMainException:
    def test_exception_alerts_and_prints_traceback_to_stderr(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        ntfy_calls: list[dict[str, Any]],
    ) -> None:
        _stub_pipeline(monkeypatch, ValueError("recipient_email is not configured"))

        assert run_module.main() == 1

        captured = capsys.readouterr()
        # stdout carries the message, not just the class name.
        assert captured.out.strip() == "FAIL: ValueError: recipient_email is not configured"
        # Full traceback goes to stderr (journald under systemd).
        assert "Traceback (most recent call last)" in captured.err
        assert "fake_run_pipeline" in captured.err
        assert "ValueError: recipient_email is not configured" in captured.err

        assert len(ntfy_calls) == 1
        assert ntfy_calls[0]["message"] == (
            "run failed: ValueError: recipient_email is not configured"
        )

    def test_multiline_message_is_flattened_and_truncated(
        self,
        monkeypatch: pytest.MonkeyPatch,
        ntfy_calls: list[dict[str, Any]],
    ) -> None:
        _stub_pipeline(monkeypatch, RuntimeError("first line\nsecond line " + "x" * 500))

        assert run_module.main() == 1

        message = ntfy_calls[0]["message"]
        assert "\n" not in message
        assert message.startswith("run failed: RuntimeError: first line second line x")
        assert len(message) <= 200


class TestAlertIsBestEffort:
    def test_send_ntfy_raising_does_not_escape_main(
        self, monkeypatch: pytest.MonkeyPatch, ntfy_calls: list[dict[str, Any]]
    ) -> None:
        def boom(*args: Any, **kwargs: Any) -> bool:
            raise RuntimeError("ntfy exploded")

        monkeypatch.setattr("hyacine.ops.monitoring.send_ntfy", boom)
        _stub_pipeline(monkeypatch, _record(RunStatus.FAILED, error_traceback=_TB))

        assert run_module.main() == 1

    def test_settings_failure_does_not_escape_main(
        self, monkeypatch: pytest.MonkeyPatch, ntfy_calls: list[dict[str, Any]]
    ) -> None:
        def bad_settings() -> None:
            raise RuntimeError("bad .env")

        monkeypatch.setattr(run_module, "_get_settings", bad_settings)
        _stub_pipeline(monkeypatch, RuntimeError("pipeline broke"))

        assert run_module.main() == 1
        assert ntfy_calls == []

    def test_empty_topic_makes_no_network_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With HYACINE_NTFY_TOPIC unset the real send_ntfy is a no-op."""
        from hyacine.config import Settings

        monkeypatch.setattr(
            run_module, "_get_settings", lambda: Settings.model_construct(ntfy_topic="")
        )
        client_cls = MagicMock()
        monkeypatch.setattr("hyacine.ops.monitoring.httpx.Client", client_cls)
        _stub_pipeline(monkeypatch, _record(RunStatus.FAILED, error_traceback=_TB))

        assert run_module.main() == 1
        client_cls.assert_not_called()


def _graph_error(status: int) -> GraphHTTPError:
    request = httpx.Request("POST", "https://graph.microsoft.com/v1.0/me/sendMail")
    response = httpx.Response(status, request=request)
    return GraphHTTPError(f"HTTP {status}", request=request, response=response)


def _exc_id(exc: Exception) -> str:
    if isinstance(exc, GraphHTTPError):
        return f"HTTP{exc.response.status_code}"
    return type(exc).__name__


class TestDeliveryUncertain:
    """Only errors where Graph may have accepted the POST count as uncertain."""

    @pytest.mark.parametrize(
        "exc",
        [
            httpx.ReadTimeout("timed out"),
            httpx.ReadError("connection reset"),
            httpx.RemoteProtocolError("server disconnected"),
            httpx.WriteTimeout("timed out"),
            _graph_error(500),
            _graph_error(502),
            _graph_error(504),
        ],
        ids=_exc_id,
    )
    def test_may_have_been_accepted(self, exc: Exception) -> None:
        assert run_module._delivery_uncertain(exc) is True

    @pytest.mark.parametrize(
        "exc",
        [
            _graph_error(503),  # still 503 after the in-process retries
            _graph_error(429),
            _graph_error(400),
            _graph_error(403),
            httpx.ConnectError("name resolution failed"),
            httpx.ConnectTimeout("timed out"),
            httpx.PoolTimeout("timed out"),
            RuntimeError("token refresh failed"),
            ValueError("render failed"),
        ],
        ids=_exc_id,
    )
    def test_refused_or_never_sent_is_retry_safe(self, exc: Exception) -> None:
        assert run_module._delivery_uncertain(exc) is False


_TB_AADSTS = (
    "Traceback (most recent call last):\n"
    '  File "run.py", line 211, in run_pipeline\n'
    "    cred, _ = load_or_create_record(\n"
    "              ^^^^^^^^^^^^^^^^^^^^^^\n"
    '  File "get_token_mixin.py", line 117, in get_token\n'
    "    raise ClientAuthenticationError(message=msg)\n"
    "azure.core.exceptions.ClientAuthenticationError: DeviceCodeCredential.get_token "
    "failed: AADSTS70043: The refresh token has expired.\n"
    "Trace ID: 0000-1111\n"
    "Correlation ID: 2222-3333\n"
    "Timestamp: 2026-10-17 01:00:00Z\n"
)


class TestExceptionSummary:
    def test_single_line_message(self) -> None:
        assert run_module._exception_summary(_TB) == "RuntimeError: SMTP error"

    def test_multi_line_message_is_kept_whole(self) -> None:
        summary = run_module._exception_summary(_TB_AADSTS)

        assert summary == (
            "azure.core.exceptions.ClientAuthenticationError: DeviceCodeCredential."
            "get_token failed: AADSTS70043: The refresh token has expired. "
            "Trace ID: 0000-1111 Correlation ID: 2222-3333 Timestamp: 2026-10-17 01:00:00Z"
        )

    def test_real_chained_traceback_gives_only_the_final_exception(self) -> None:
        def fail() -> None:
            try:
                raise KeyError("inner")
            except KeyError as exc:
                raise ValueError("outer line one\n  outer line two") from exc

        try:
            fail()
        except ValueError:
            tb = traceback.format_exc()

        assert "KeyError" in tb  # the chained cause is in the traceback...
        # ...but the summary is the final exception, whitespace-collapsed.
        assert run_module._exception_summary(tb) == "ValueError: outer line one outer line two"

    def test_text_without_frames_is_collapsed_whole(self) -> None:
        assert run_module._exception_summary("  boom\n  again \n") == "boom again"


class TestMainUncertainDelivery:
    def _uncertain_record(self) -> RunRecord:
        tb = (
            "Traceback (most recent call last):\n"
            '  File "send.py", line 173, in send_email\n'
            "    resp = request_with_retry(\n"
            "httpx.ReadTimeout: The read operation timed out\n"
            f"{run_module._DELIVERY_UNKNOWN_NOTE}\n"
        )
        return _record(RunStatus.FAILED, error_traceback=tb, delivery_uncertain=True)

    def test_returns_no_retry_status_and_alerts(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        ntfy_calls: list[dict[str, Any]],
    ) -> None:
        _stub_pipeline(monkeypatch, self._uncertain_record())

        assert run_module.main() == run_module.EXIT_NO_RETRY == 3

        assert capsys.readouterr().out.strip() == (
            "FAIL: httpx.ReadTimeout: The read operation timed out "
            "(delivery outcome unknown: not retrying)"
        )
        assert [c["message"] for c in ntfy_calls] == [
            "run 7 failed: sendMail outcome unknown, not retrying - check the inbox "
            "(httpx.ReadTimeout: The read operation timed out)"
        ]

    def test_failed_record_without_the_flag_returns_one(
        self, monkeypatch: pytest.MonkeyPatch, ntfy_calls: list[dict[str, Any]]
    ) -> None:
        _stub_pipeline(monkeypatch, _record(RunStatus.FAILED, error_traceback=_TB))

        assert run_module.main() == 1
        assert "outcome unknown" not in ntfy_calls[0]["message"]

    def test_multi_line_failure_alerts_with_the_useful_part(
        self, monkeypatch: pytest.MonkeyPatch, ntfy_calls: list[dict[str, Any]]
    ) -> None:
        _stub_pipeline(monkeypatch, _record(RunStatus.FAILED, error_traceback=_TB_AADSTS))

        assert run_module.main() == 1

        message = ntfy_calls[0]["message"]
        assert message.startswith("run 7 failed: azure.core.exceptions.ClientAuthenticationError")
        assert "AADSTS70043" in message
        assert len(message) <= 200


class TestMainDeliveredButNotRecorded:
    def _exc(self, *, watermark_advanced: bool = False) -> run_module.DeliveredButNotRecorded:
        exc = run_module.DeliveredButNotRecorded(
            "req-123", watermark_advanced=watermark_advanced
        )
        exc.__cause__ = sqlite3.OperationalError("database is locked")
        return exc

    def test_returns_no_retry_status_and_alerts(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        ntfy_calls: list[dict[str, Any]],
    ) -> None:
        _stub_pipeline(monkeypatch, self._exc())

        assert run_module.main() == run_module.EXIT_NO_RETRY

        captured = capsys.readouterr()
        # Full traceback, original error included, goes to stderr.
        assert "OperationalError: database is locked" in captured.err
        assert "DeliveredButNotRecorded" in captured.err
        assert captured.out.strip() == (
            "FAIL: digest sent (sent_message_id=req-123) but the run was not recorded; "
            "watermark not advanced: OperationalError: database is locked"
        )
        assert [c["message"] for c in ntfy_calls] == [
            "digest sent but the run was not recorded; watermark not advanced "
            "(OperationalError: database is locked)"
        ]

    def test_alert_says_when_the_watermark_did_advance(
        self, monkeypatch: pytest.MonkeyPatch, ntfy_calls: list[dict[str, Any]]
    ) -> None:
        _stub_pipeline(monkeypatch, self._exc(watermark_advanced=True))

        assert run_module.main() == run_module.EXIT_NO_RETRY
        assert "; watermark advanced (" in ntfy_calls[0]["message"]

    def test_carries_sent_message_id(self) -> None:
        exc = self._exc()
        assert exc.sent_message_id == "req-123"
        assert exc.watermark_advanced is False


class TestSigterm:
    def test_handler_raises_run_terminated(self) -> None:
        with pytest.raises(run_module.RunTerminated, match="terminated by SIGTERM"):
            run_module._on_sigterm(signal.SIGTERM, None)

    def test_run_terminated_is_an_exception(self) -> None:
        # The phase handlers in run_pipeline catch Exception; a BaseException
        # would slip past them and leave the run row RUNNING.
        assert issubclass(run_module.RunTerminated, Exception)

    def test_main_installs_handler_during_the_run_and_restores_it(
        self, monkeypatch: pytest.MonkeyPatch, ntfy_calls: list[dict[str, Any]]
    ) -> None:
        before = signal.getsignal(signal.SIGTERM)
        seen: list[object] = []

        def fake_run_pipeline(*args: Any, **kwargs: Any) -> RunRecord:
            seen.append(signal.getsignal(signal.SIGTERM))
            return _record(RunStatus.SUCCESS, sent_message_id="msg-1")

        monkeypatch.setattr(run_module, "run_pipeline", fake_run_pipeline)

        assert run_module.main() == 0
        assert seen == [run_module._on_sigterm]
        assert signal.getsignal(signal.SIGTERM) == before

    def test_run_terminated_outside_a_phase_returns_one(
        self, monkeypatch: pytest.MonkeyPatch, ntfy_calls: list[dict[str, Any]]
    ) -> None:
        _stub_pipeline(
            monkeypatch,
            run_module.RunTerminated("terminated by SIGTERM (systemd TimeoutStartSec or stop)"),
        )

        assert run_module.main() == 1
        assert ntfy_calls[0]["message"] == (
            "run failed: RunTerminated: terminated by SIGTERM "
            "(systemd TimeoutStartSec or stop)"
        )
