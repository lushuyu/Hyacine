"""Tests for the CLI entry ``hyacine.pipeline.run.main`` — exit codes, output,
and the best-effort ntfy failure alert. ``run_pipeline`` is always stubbed.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

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
