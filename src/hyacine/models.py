"""Pydantic data models — the frozen public contract for the hyacine pipeline.

These shapes are consumed by every module: graph fetch returns these, pipeline
hands them to LLM wrappers, DB persists them, Web UI reads them back.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CategoryHint(StrEnum):
    ADVISOR = "advisor"
    GRAD_SCHOOL = "grad_school"
    ARXIV = "arxiv"
    SCHOLAR = "scholar"
    CFP = "cfp"
    CANVAS = "canvas"
    ADMIN = "admin"
    NEWSLETTER = "newsletter"
    OTHER = "other"


class Importance(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class EmailMessage(BaseModel):
    """One Microsoft Graph message, trimmed to fields we actually use."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="Graph message id (stable, opaque)")
    subject: str = ""
    sender_name: str = ""
    sender_email: str = ""
    sender_domain: str = Field(
        default="",
        description="lowercased domain part of sender_email; filled by fetch layer",
    )
    received_at: datetime
    body_preview: str = Field(default="", description="first ~255 chars, plain text")
    importance: Importance = Importance.NORMAL
    is_read: bool = False
    web_link: str | None = None
    category_hint: CategoryHint = CategoryHint.OTHER


class EventAttendee(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    email: str = ""
    response: str = "none"


class CalendarEvent(BaseModel):
    """One Microsoft Graph calendar event."""

    model_config = ConfigDict(extra="ignore")

    id: str
    subject: str = ""
    start: datetime
    end: datetime
    location: str = ""
    is_all_day: bool = False
    attendees: list[EventAttendee] = Field(default_factory=list)
    web_link: str | None = None


class FetchResult(BaseModel):
    """Payload fed into the LLM — represents everything we pulled for one run."""

    model_config = ConfigDict(extra="ignore")

    window_from: datetime
    window_to: datetime
    emails: list[EmailMessage] = Field(default_factory=list)
    calendar_today: list[CalendarEvent] = Field(default_factory=list)
    generated_at: datetime


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class HcPingResult(StrEnum):
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"


class RunRecord(BaseModel):
    """DB row for one end-to-end pipeline run."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    started_at: datetime
    finished_at: datetime | None = None
    status: RunStatus = RunStatus.PENDING
    window_from: datetime
    window_to: datetime
    email_count: int = 0
    markdown: str | None = None
    error_traceback: str | None = None
    hc_ping_result: HcPingResult = HcPingResult.SKIPPED
    sent_message_id: str | None = None


class ConfigSnapshot(BaseModel):
    """Versioned snapshot of editable config (prompt template or rules yaml)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    kind: str = Field(description="'prompt' or 'rules'")
    created_at: datetime
    content: str
    note: str = ""
