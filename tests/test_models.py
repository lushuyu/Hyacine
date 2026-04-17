"""Smoke tests for the frozen pydantic contract."""
from __future__ import annotations

from datetime import UTC, datetime

from hyacine.models import (
    BriefingRunRecord,
    CalendarEvent,
    CategoryHint,
    EmailMessage,
    FetchResult,
    HcPingResult,
    Importance,
    RunStatus,
)


def test_email_defaults() -> None:
    msg = EmailMessage(id="abc", received_at=datetime(2026, 4, 17, 0, 0, tzinfo=UTC))
    assert msg.category_hint is CategoryHint.OTHER
    assert msg.importance is Importance.NORMAL
    assert msg.is_read is False


def test_fetch_result_round_trip() -> None:
    now = datetime.now(tz=UTC)
    fr = FetchResult(window_from=now, window_to=now, generated_at=now)
    data = fr.model_dump_json()
    restored = FetchResult.model_validate_json(data)
    assert restored.emails == []
    assert restored.calendar_today == []


def test_run_record_defaults() -> None:
    now = datetime.now(tz=UTC)
    rec = BriefingRunRecord(started_at=now, window_from=now, window_to=now)
    assert rec.status is RunStatus.PENDING
    assert rec.hc_ping_result is HcPingResult.SKIPPED
    assert rec.email_count == 0


def test_calendar_event_shape() -> None:
    now = datetime.now(tz=UTC)
    ev = CalendarEvent(id="e1", start=now, end=now)
    assert ev.attendees == []
    assert ev.is_all_day is False
