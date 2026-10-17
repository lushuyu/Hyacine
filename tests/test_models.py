"""Smoke tests for the frozen pydantic contract."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from hyacine.models import (
    LLM_ATTENDEE_CAP,
    CalendarEvent,
    CategoryHint,
    EmailMessage,
    EventAttendee,
    FetchResult,
    HcPingResult,
    Importance,
    RunRecord,
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
    rec = RunRecord(started_at=now, window_from=now, window_to=now)
    assert rec.status is RunStatus.PENDING
    assert rec.hc_ping_result is HcPingResult.SKIPPED
    assert rec.email_count == 0


def test_calendar_event_shape() -> None:
    now = datetime.now(tz=UTC)
    ev = CalendarEvent(id="e1", start=now, end=now)
    assert ev.attendees == []
    assert ev.is_all_day is False


def _llm_fetch_result() -> FetchResult:
    now = datetime(2026, 4, 17, 0, 0, tzinfo=UTC)
    email = EmailMessage(
        id="AAMkAG" + "x" * 150,
        subject="项目周报：请审阅第三季度预算",
        sender_name="王小明",
        sender_email="wang@example.cn",
        sender_domain="example.cn",
        received_at=now,
        body_preview="本周进展顺利，请在周五前反馈。",
        web_link="https://outlook.office365.com/owa/?ItemID=abc",
        category_hint=CategoryHint.PRIORITY,
    )
    big = CalendarEvent(
        id="AAMkAGevent" + "y" * 150,
        subject="全员大会",
        start=now,
        end=now,
        attendees=[
            EventAttendee(name=f"Person {i}", email=f"p{i}@example.com")
            for i in range(LLM_ATTENDEE_CAP + 5)
        ],
        web_link="https://outlook.office365.com/calendar/item/big",
    )
    small = CalendarEvent(
        id="AAMkAGevent2",
        subject="1:1",
        start=now,
        end=now,
        attendees=[EventAttendee(name="Bob", email="bob@example.com")],
    )
    return FetchResult(
        window_from=now,
        window_to=now,
        emails=[email],
        calendar_today=[big, small],
        generated_at=now,
    )


def test_to_llm_json_drops_opaque_fields_and_keeps_web_link() -> None:
    fr = _llm_fetch_result()
    data = json.loads(fr.to_llm_json())

    [email] = data["emails"]
    assert "id" not in email
    assert "sender_domain" not in email
    assert email["sender_email"] == "wang@example.cn"
    assert email["category_hint"] == "priority"
    assert email["web_link"] == "https://outlook.office365.com/owa/?ItemID=abc"

    assert all("id" not in event for event in data["calendar_today"])
    assert data["calendar_today"][0]["web_link"] == (
        "https://outlook.office365.com/calendar/item/big"
    )
    assert data["window_from"] == "2026-04-17T00:00:00Z"


def test_to_llm_json_caps_attendees() -> None:
    fr = _llm_fetch_result()
    big, small = json.loads(fr.to_llm_json())["calendar_today"]

    assert len(big["attendees"]) == LLM_ATTENDEE_CAP
    assert big["attendees"][0] == {
        "name": "Person 0", "email": "p0@example.com", "response": "none"
    }
    assert big["attendee_count"] == LLM_ATTENDEE_CAP + 5

    assert len(small["attendees"]) == 1
    assert "attendee_count" not in small
    # The source model is untouched.
    assert len(fr.calendar_today[0].attendees) == LLM_ATTENDEE_CAP + 5


def test_to_llm_json_keeps_cjk_unescaped_and_is_smaller() -> None:
    fr = _llm_fetch_result()
    payload = fr.to_llm_json()

    assert "项目周报：请审阅第三季度预算" in payload
    assert "王小明" in payload
    assert "\\u" not in payload
    assert len(payload.encode("utf-8")) < len(fr.model_dump_json().encode("utf-8"))


def test_model_dump_json_stays_lossless() -> None:
    fr = _llm_fetch_result()
    restored = FetchResult.model_validate_json(fr.model_dump_json())
    assert restored == fr
    assert restored.emails[0].id.startswith("AAMkAG")
    assert len(restored.calendar_today[0].attendees) == LLM_ATTENDEE_CAP + 5


def test_to_llm_json_empty_result() -> None:
    now = datetime(2026, 4, 17, 0, 0, tzinfo=UTC)
    fr = FetchResult(window_from=now, window_to=now, generated_at=now)
    data = json.loads(fr.to_llm_json())
    assert data["emails"] == []
    assert data["calendar_today"] == []
