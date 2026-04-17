"""Tests for watermark lifecycle and end-to-end pipeline gating."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hyacine import db as db_module
from hyacine.db import init_db
from hyacine.models import EmailMessage, RunStatus
from hyacine.pipeline import briefing as briefing_module

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect settings to use a tmp_path DB and a minimal prompt file."""
    db_path = tmp_path / "test.db"
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("You are a helpful assistant.")

    # Reset cached singletons so each test gets fresh settings
    monkeypatch.setattr(briefing_module, "_settings", None)
    monkeypatch.setattr(briefing_module, "_cfg", None)

    # Reset the DB engine singleton so each test gets a fresh DB
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
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
    )
    fake_cfg = YamlConfig(
        recipient_email="test@example.com",
        timezone="UTC",
        llm_model="sonnet",
        llm_timeout_seconds=10,
        initial_watermark_lookback_hours=24,
    )

    monkeypatch.setattr(briefing_module, "_get_settings", lambda: fake_settings)
    monkeypatch.setattr(briefing_module, "_get_cfg", lambda: fake_cfg)

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


# ---------------------------------------------------------------------------
# test_first_run_backfills_24h
# ---------------------------------------------------------------------------

class TestWatermarkFirstRun:
    def test_first_run_backfills_24h(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_path = _patch_settings(monkeypatch, tmp_path)

        before = datetime.now(UTC)
        wm = briefing_module.read_watermark()
        after = datetime.now(UTC)

        # Should be approximately now - 24h
        expected_low = before - timedelta(hours=24, seconds=5)
        expected_high = after - timedelta(hours=24) + timedelta(seconds=5)

        assert wm.tzinfo is not None, "watermark must be timezone-aware"
        assert expected_low <= wm <= expected_high, (
            f"Expected watermark ~24h ago, got {wm}"
        )

        # Row must have been persisted
        from hyacine.db import Watermark, session_scope
        with session_scope(db_path) as session:
            row = session.get(Watermark, "last_successful_run_at")
        assert row is not None, "watermark row must be persisted after first read"

        # Second call returns the same value (not a fresh backfill)
        wm2 = briefing_module.read_watermark()
        assert abs((wm2 - wm).total_seconds()) < 2, (
            "Second read should return same persisted value"
        )


# ---------------------------------------------------------------------------
# test_watermark_only_advances_on_send_success
# ---------------------------------------------------------------------------

class TestWatermarkAdvancesOnlyOnSuccess:
    def test_watermark_not_advanced_when_send_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_settings(monkeypatch, tmp_path)

        now_utc = datetime(2024, 6, 15, 2, 0, 0, tzinfo=UTC)

        # Patch all external dependencies
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
            "hyacine.pipeline.briefing.summarize",
            lambda *a, **kw: "# Daily Briefing\nContent here.",
        )
        monkeypatch.setattr(
            "hyacine.graph.send.send_briefing_email",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("SMTP error")),
        )
        # Swallow rules load errors (no rules file in tmp_path)
        monkeypatch.setattr(
            "hyacine.pipeline.rules.load_rules",
            lambda *a, **kw: __import__(
                "hyacine.pipeline.rules", fromlist=["RuleSet"]
            ).RuleSet(),
        )

        initial_wm = briefing_module.read_watermark()

        record = briefing_module.run_briefing(now_utc=now_utc)

        assert record.status == RunStatus.FAILED
        # briefing_markdown should still be stored even when send failed
        assert record.briefing_markdown == "# Daily Briefing\nContent here."

        # Watermark must NOT have advanced
        wm_after = briefing_module.read_watermark()
        assert abs((wm_after - initial_wm).total_seconds()) < 2, (
            f"Watermark should not advance on send failure; "
            f"initial={initial_wm}, after={wm_after}"
        )

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
            "hyacine.pipeline.briefing.summarize",
            lambda *a, **kw: "# Daily Briefing\nContent here.",
        )
        monkeypatch.setattr(
            "hyacine.graph.send.send_briefing_email",
            lambda *a, **kw: "msg-id-001",
        )
        monkeypatch.setattr(
            "hyacine.pipeline.rules.load_rules",
            lambda *a, **kw: __import__(
                "hyacine.pipeline.rules", fromlist=["RuleSet"]
            ).RuleSet(),
        )

        record = briefing_module.run_briefing(now_utc=now_utc)

        assert record.status == RunStatus.SUCCESS
        assert record.sent_message_id == "msg-id-001"
        assert record.email_count == 1

        # Watermark should now equal now_utc
        wm_after = briefing_module.read_watermark()
        assert abs((wm_after - now_utc).total_seconds()) < 2, (
            f"Watermark should advance to now_utc={now_utc}, got {wm_after}"
        )

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
            "hyacine.pipeline.briefing.summarize",
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

        initial_wm = briefing_module.read_watermark()
        record = briefing_module.run_briefing(now_utc=now_utc)

        assert record.status == RunStatus.FAILED
        wm_after = briefing_module.read_watermark()
        assert abs((wm_after - initial_wm).total_seconds()) < 2, (
            "Watermark should not advance when LLM fails"
        )

    def test_watermark_not_advanced_when_fetch_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_settings(monkeypatch, tmp_path)

        now_utc = datetime(2024, 6, 15, 4, 0, 0, tzinfo=UTC)

        monkeypatch.setattr(
            "hyacine.graph.auth.load_or_create_record",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("auth error")),
        )

        initial_wm = briefing_module.read_watermark()
        record = briefing_module.run_briefing(now_utc=now_utc)

        assert record.status == RunStatus.FAILED
        wm_after = briefing_module.read_watermark()
        assert abs((wm_after - initial_wm).total_seconds()) < 2, (
            "Watermark should not advance when fetch fails"
        )
