"""Tests for watermark lifecycle and end-to-end pipeline gating."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hyacine import db as db_module
from hyacine.db import init_db
from hyacine.models import EmailMessage, RunStatus
from hyacine.pipeline import run as run_module


def _patch_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect settings to use a tmp_path DB and a minimal prompt file."""
    db_path = tmp_path / "test.db"
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("You are a helpful assistant.")

    monkeypatch.setattr(run_module, "_settings", None)
    monkeypatch.setattr(run_module, "_cfg", None)

    monkeypatch.setattr(db_module, "_engine", None)
    monkeypatch.setattr(db_module, "_SessionFactory", None)

    from hyacine.config import Settings, YamlConfig

    fake_settings = Settings.model_construct(
        db_path=db_path,
        prompt_path=prompt_path,
        rules_path=tmp_path / "rules.yaml",
        healthchecks_uuid="",
        graph_client_id="fake-client-id",
        graph_tenant_id="fake-tenant-id",
        graph_scopes="User.Read",
        auth_dir=tmp_path / "auth",
        ntfy_topic="",
        config_path=tmp_path / "config.yaml",
        log_dir=tmp_path / "logs",
        auth_record_path=tmp_path / "auth" / "auth_record.json",
    )
    fake_cfg = YamlConfig(
        recipient_email="test@example.com",
        timezone="UTC",
        llm_model="sonnet",
        llm_timeout_seconds=10,
        initial_watermark_lookback_hours=24,
    )

    monkeypatch.setattr(run_module, "_get_settings", lambda: fake_settings)
    monkeypatch.setattr(run_module, "_get_cfg", lambda: fake_cfg)

    init_db(db_path)
    return db_path


def _make_email() -> EmailMessage:
    return EmailMessage(
        id="e1",
        subject="Test",
        sender_email="a@b.com",
        sender_domain="b.com",
        received_at=datetime(2024, 1, 1, 8, 0, tzinfo=UTC),
    )


class TestWatermarkFirstRun:
    def test_first_run_backfills_24h(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_path = _patch_settings(monkeypatch, tmp_path)

        before = datetime.now(UTC)
        wm = run_module.read_watermark()
        after = datetime.now(UTC)

        expected_low = before - timedelta(hours=24, seconds=5)
        expected_high = after - timedelta(hours=24) + timedelta(seconds=5)

        assert wm.tzinfo is not None
        assert expected_low <= wm <= expected_high

        from hyacine.db import Watermark, session_scope
        with session_scope(db_path) as session:
            row = session.get(Watermark, "last_successful_run_at")
        assert row is not None

        wm2 = run_module.read_watermark()
        assert abs((wm2 - wm).total_seconds()) < 2


class TestWatermarkAdvancesOnlyOnSuccess:
    def test_watermark_not_advanced_when_send_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_settings(monkeypatch, tmp_path)

        now_utc = datetime(2024, 6, 15, 2, 0, 0, tzinfo=UTC)

        monkeypatch.setattr(
            "hyacine.graph.auth.load_or_create_record",
            lambda *a, **kw: (object(), object()),
        )
        monkeypatch.setattr(
            "hyacine.graph.fetch.fetch_emails",
            lambda *a, **kw: [_make_email()],
        )
        monkeypatch.setattr(
            "hyacine.graph.fetch.fetch_calendar",
            lambda *a, **kw: [],
        )
        monkeypatch.setattr(
            "hyacine.pipeline.run.summarize",
            lambda *a, **kw: "# Daily report\nContent here.",
        )
        monkeypatch.setattr(
            "hyacine.graph.send.send_email",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("SMTP error")),
        )
        monkeypatch.setattr(
            "hyacine.pipeline.rules.load_rules",
            lambda *a, **kw: __import__(
                "hyacine.pipeline.rules", fromlist=["RuleSet"]
            ).RuleSet(),
        )

        initial_wm = run_module.read_watermark()

        record = run_module.run_pipeline(now_utc=now_utc)

        assert record.status == RunStatus.FAILED
        assert record.markdown == "# Daily report\nContent here."

        wm_after = run_module.read_watermark()
        assert abs((wm_after - initial_wm).total_seconds()) < 2

    def test_watermark_advances_when_send_succeeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_settings(monkeypatch, tmp_path)

        now_utc = datetime(2024, 6, 15, 2, 0, 0, tzinfo=UTC)

        monkeypatch.setattr(
            "hyacine.graph.auth.load_or_create_record",
            lambda *a, **kw: (object(), object()),
        )
        monkeypatch.setattr(
            "hyacine.graph.fetch.fetch_emails",
            lambda *a, **kw: [_make_email()],
        )
        monkeypatch.setattr(
            "hyacine.graph.fetch.fetch_calendar",
            lambda *a, **kw: [],
        )
        monkeypatch.setattr(
            "hyacine.pipeline.run.summarize",
            lambda *a, **kw: "# Daily report\nContent here.",
        )
        monkeypatch.setattr(
            "hyacine.graph.send.send_email",
            lambda *a, **kw: "msg-id-001",
        )
        monkeypatch.setattr(
            "hyacine.pipeline.rules.load_rules",
            lambda *a, **kw: __import__(
                "hyacine.pipeline.rules", fromlist=["RuleSet"]
            ).RuleSet(),
        )

        record = run_module.run_pipeline(now_utc=now_utc)

        assert record.status == RunStatus.SUCCESS
        assert record.sent_message_id == "msg-id-001"
        assert record.email_count == 1

        wm_after = run_module.read_watermark()
        assert abs((wm_after - now_utc).total_seconds()) < 2

    def test_llm_receives_trimmed_payload(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_settings(monkeypatch, tmp_path)
        captured: dict[str, str] = {}

        def fake_summarize(json_input: str, *a: object, **kw: object) -> str:
            captured["json"] = json_input
            return "# Daily report"

        monkeypatch.setattr(
            "hyacine.graph.auth.load_or_create_record",
            lambda *a, **kw: (object(), object()),
        )
        monkeypatch.setattr(
            "hyacine.graph.fetch.fetch_emails",
            lambda *a, **kw: [_make_email()],
        )
        monkeypatch.setattr(
            "hyacine.graph.fetch.fetch_calendar",
            lambda *a, **kw: [],
        )
        monkeypatch.setattr("hyacine.pipeline.run.summarize", fake_summarize)
        monkeypatch.setattr(
            "hyacine.graph.send.send_email",
            lambda *a, **kw: "msg-id-001",
        )

        run_module.run_pipeline(now_utc=datetime(2024, 6, 15, 2, 0, 0, tzinfo=UTC))

        import json

        email = json.loads(captured["json"])["emails"][0]
        assert email["subject"] == "Test"
        assert "id" not in email
        assert "sender_domain" not in email

    def test_watermark_not_advanced_when_llm_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_settings(monkeypatch, tmp_path)

        now_utc = datetime(2024, 6, 15, 3, 0, 0, tzinfo=UTC)

        monkeypatch.setattr(
            "hyacine.graph.auth.load_or_create_record",
            lambda *a, **kw: (object(), object()),
        )
        monkeypatch.setattr(
            "hyacine.graph.fetch.fetch_emails",
            lambda *a, **kw: [],
        )
        monkeypatch.setattr(
            "hyacine.graph.fetch.fetch_calendar",
            lambda *a, **kw: [],
        )
        monkeypatch.setattr(
            "hyacine.pipeline.run.summarize",
            lambda *a, **kw: (_ for _ in ()).throw(
                __import__(
                    "hyacine.llm.claude_code", fromlist=["ClaudeCodeError"]
                ).ClaudeCodeError("LLM timed out")
            ),
        )
        monkeypatch.setattr(
            "hyacine.pipeline.rules.load_rules",
            lambda *a, **kw: __import__(
                "hyacine.pipeline.rules", fromlist=["RuleSet"]
            ).RuleSet(),
        )

        initial_wm = run_module.read_watermark()
        record = run_module.run_pipeline(now_utc=now_utc)

        assert record.status == RunStatus.FAILED
        wm_after = run_module.read_watermark()
        assert abs((wm_after - initial_wm).total_seconds()) < 2

    def test_watermark_not_advanced_when_fetch_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_settings(monkeypatch, tmp_path)

        now_utc = datetime(2024, 6, 15, 4, 0, 0, tzinfo=UTC)

        monkeypatch.setattr(
            "hyacine.graph.auth.load_or_create_record",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("auth error")),
        )

        initial_wm = run_module.read_watermark()
        record = run_module.run_pipeline(now_utc=now_utc)

        assert record.status == RunStatus.FAILED
        wm_after = run_module.read_watermark()
        assert abs((wm_after - initial_wm).total_seconds()) < 2


class TestPipelineForwardsEmailContext:
    """The pipeline must pass model + localized date/weekday/time + language
    into ``send_email`` so the modern email footer reflects the run config.
    """

    def test_send_email_receives_render_context(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_settings(monkeypatch, tmp_path)

        # Override the YAML config to a non-default language + tz so we can
        # see the values land in the captured kwargs.
        from hyacine.config import YamlConfig

        cfg = YamlConfig(
            recipient_email="alice@example.com",
            timezone="Asia/Singapore",
            llm_model="claude-sonnet-4-5",
            llm_timeout_seconds=10,
            initial_watermark_lookback_hours=24,
            language="zh-CN",
        )
        monkeypatch.setattr(run_module, "_get_cfg", lambda: cfg)

        now_utc = datetime(2024, 6, 14, 23, 31, 0, tzinfo=UTC)  # Sat in SGT

        monkeypatch.setattr(
            "hyacine.graph.auth.load_or_create_record",
            lambda *a, **kw: (object(), object()),
        )
        monkeypatch.setattr(
            "hyacine.graph.fetch.fetch_emails",
            lambda *a, **kw: [_make_email()],
        )
        monkeypatch.setattr(
            "hyacine.graph.fetch.fetch_calendar",
            lambda *a, **kw: [],
        )
        monkeypatch.setattr(
            "hyacine.pipeline.run.summarize",
            lambda *a, **kw: "# Daily report\n\nbody",
        )
        monkeypatch.setattr(
            "hyacine.pipeline.rules.load_rules",
            lambda *a, **kw: __import__(
                "hyacine.pipeline.rules", fromlist=["RuleSet"]
            ).RuleSet(),
        )

        captured: dict[str, object] = {}

        def fake_send(
            cred, recipient, subject, markdown_body, **kwargs
        ):  # type: ignore[override]
            captured["recipient"] = recipient
            captured["subject"] = subject
            captured.update(kwargs)
            return "msg-id-zh"

        monkeypatch.setattr("hyacine.graph.send.send_email", fake_send)

        record = run_module.run_pipeline(now_utc=now_utc)
        assert record.status == RunStatus.SUCCESS

        # Local time in Asia/Singapore is +08:00 → 2024-06-15 07:31 Saturday.
        assert captured["model"] == "claude-sonnet-4-5"
        assert captured["date"] == "2024-06-15"
        assert captured["generated_at"] == "07:31"
        assert captured["weekday"] == "星期六"  # zh-CN Saturday
        assert captured["language"] == "zh-CN"

    def test_send_email_receives_english_weekday_when_lang_en(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_settings(monkeypatch, tmp_path)
        from hyacine.config import YamlConfig

        cfg = YamlConfig(
            recipient_email="alice@example.com",
            timezone="UTC",
            llm_model="gpt-4.1",
            llm_timeout_seconds=10,
            language="en",
        )
        monkeypatch.setattr(run_module, "_get_cfg", lambda: cfg)
        now_utc = datetime(2024, 6, 14, 12, 0, 0, tzinfo=UTC)  # Friday UTC

        monkeypatch.setattr(
            "hyacine.graph.auth.load_or_create_record",
            lambda *a, **kw: (object(), object()),
        )
        monkeypatch.setattr(
            "hyacine.graph.fetch.fetch_emails", lambda *a, **kw: [_make_email()]
        )
        monkeypatch.setattr(
            "hyacine.graph.fetch.fetch_calendar", lambda *a, **kw: []
        )
        monkeypatch.setattr(
            "hyacine.pipeline.run.summarize", lambda *a, **kw: "# x\n"
        )
        monkeypatch.setattr(
            "hyacine.pipeline.rules.load_rules",
            lambda *a, **kw: __import__(
                "hyacine.pipeline.rules", fromlist=["RuleSet"]
            ).RuleSet(),
        )

        captured: dict[str, object] = {}

        def fake_send(cred, recipient, subject, markdown_body, **kwargs):
            captured.update(kwargs)
            return "msg-id-en"

        monkeypatch.setattr("hyacine.graph.send.send_email", fake_send)

        run_module.run_pipeline(now_utc=now_utc)

        assert captured["weekday"] == "Friday"
        assert captured["language"] == "en"
        assert captured["model"] == "gpt-4.1"


class TestRulesLoadFailureIsNonFatal:
    """A broken or missing rules file must not fail the run, but it must no
    longer be silent: one warning line on stderr naming the error.
    """

    def _patch_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "hyacine.graph.auth.load_or_create_record",
            lambda *a, **kw: (object(), object()),
        )
        monkeypatch.setattr(
            "hyacine.graph.fetch.fetch_emails",
            lambda *a, **kw: [_make_email()],
        )
        monkeypatch.setattr(
            "hyacine.graph.fetch.fetch_calendar",
            lambda *a, **kw: [],
        )
        monkeypatch.setattr(
            "hyacine.pipeline.run.summarize",
            lambda *a, **kw: "# Daily report\nContent here.",
        )
        monkeypatch.setattr(
            "hyacine.graph.send.send_email",
            lambda *a, **kw: "msg-id-rules",
        )

    def test_invalid_rules_warn_and_run_succeeds(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _patch_settings(monkeypatch, tmp_path)
        self._patch_happy_path(monkeypatch)
        monkeypatch.setattr(
            "hyacine.pipeline.rules.load_rules",
            lambda *a, **kw: (_ for _ in ()).throw(
                ValueError("Invalid rules YAML at rules.yaml: 1 validation error\n  rules")
            ),
        )

        record = run_module.run_pipeline(now_utc=datetime(2024, 6, 15, 2, 0, tzinfo=UTC))

        assert record.status == RunStatus.SUCCESS
        assert record.sent_message_id == "msg-id-rules"
        err = capsys.readouterr().err
        assert err.count("\n") == 1  # exactly one line
        assert err.startswith("WARN: rules not loaded")
        assert "ValueError: Invalid rules YAML at rules.yaml: 1 validation error rules" in err

    def test_missing_rules_file_warns_with_path(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # _patch_settings points rules_path at a file that does not exist, so
        # the real load_rules raises FileNotFoundError.
        _patch_settings(monkeypatch, tmp_path)
        self._patch_happy_path(monkeypatch)

        record = run_module.run_pipeline(now_utc=datetime(2024, 6, 15, 2, 0, tzinfo=UTC))

        assert record.status == RunStatus.SUCCESS
        err = capsys.readouterr().err
        assert "FileNotFoundError" in err
        assert str(tmp_path / "rules.yaml") in err


class TestMainAlertsOnFailedRun:
    """End-to-end: a real FAILED run row reaches main()'s ntfy alert with the
    run id and the traceback's last line.
    """

    def test_fetch_failure_sends_short_ntfy_alert(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _patch_settings(monkeypatch, tmp_path)
        monkeypatch.setattr(
            "hyacine.graph.auth.load_or_create_record",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("auth error")),
        )
        sent: list[tuple[str, str]] = []
        monkeypatch.setattr(
            "hyacine.ops.monitoring.send_ntfy",
            lambda topic, message, **kw: sent.append((topic, message)) or True,
        )

        assert run_module.main() == 1

        assert capsys.readouterr().out.strip() == "FAIL: RuntimeError: auth error"
        # Topic is "" in _patch_settings; send_ntfy owns the empty-topic no-op.
        assert sent == [("", "run 1 failed: RuntimeError: auth error")]
