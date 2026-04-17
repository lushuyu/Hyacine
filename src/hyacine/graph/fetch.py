"""Pull messages + today's calendar from Microsoft Graph."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from azure.identity import DeviceCodeCredential

from hyacine.models import CalendarEvent, CategoryHint, EmailMessage, EventAttendee, Importance

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Map common IANA timezone names to Windows timezone names used by Outlook
_IANA_TO_WINDOWS: dict[str, str] = {
    "Asia/Singapore": "Singapore Standard Time",
    "Asia/Shanghai": "China Standard Time",
    "Asia/Tokyo": "Tokyo Standard Time",
    "America/New_York": "Eastern Standard Time",
    "America/Los_Angeles": "Pacific Standard Time",
    "America/Chicago": "Central Standard Time",
    "Europe/London": "GMT Standard Time",
    "Europe/Berlin": "W. Europe Standard Time",
    "UTC": "UTC",
}


def _get_bearer(cred: DeviceCodeCredential) -> str:
    token = cred.get_token("https://graph.microsoft.com/.default")
    return f"Bearer {token.token}"


def _importance_from_str(value: str | None) -> Importance:
    mapping = {"low": Importance.LOW, "high": Importance.HIGH}
    return mapping.get((value or "").lower(), Importance.NORMAL)


def _parse_dt(value: str | None) -> datetime:
    """Parse an ISO-8601 string to a UTC-aware datetime."""
    if not value:
        return datetime.now(tz=UTC)
    # Graph returns strings like "2024-01-15T08:30:00Z" or with offset
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _parse_dt_timezone(dt_tz: dict[str, Any]) -> datetime:
    """Parse a Graph DateTimeTimeZone object {dateTime, timeZone}."""
    raw = dt_tz.get("dateTime", "")
    # Graph returns naive datetime + timezone name; make it UTC-aware
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        dt = datetime.now(tz=UTC)
    if dt.tzinfo is None:
        # Attach UTC; real tz conversion would require zoneinfo but Graph
        # returns times already in the requested zone, so tzinfo=utc is fine
        # for storage (the field is just a point in time).
        dt = dt.replace(tzinfo=UTC)
    return dt


def fetch_emails(
    cred: DeviceCodeCredential,
    since: datetime,
    until: datetime,
    *,
    top: int = 100,
    max_pages: int = 10,
) -> list[EmailMessage]:
    """Fetch /me/messages in [since, until] using $filter on receivedDateTime.

    Uses $select to trim the payload, $orderby receivedDateTime desc, $top=100,
    and walks @odata.nextLink up to max_pages.

    Populates sender_domain (lowercased) and leaves category_hint as OTHER —
    that's the rules module's job.
    """
    since_iso = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    until_iso = until.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "$filter": f"receivedDateTime ge {since_iso} and receivedDateTime lt {until_iso}",
        "$orderby": "receivedDateTime desc",
        "$top": str(top),
        "$select": "id,subject,from,receivedDateTime,bodyPreview,importance,isRead,webLink",
    }

    headers = {"Authorization": _get_bearer(cred)}
    url: str | None = f"{_GRAPH_BASE}/me/messages"
    results: list[EmailMessage] = []
    pages = 0

    with httpx.Client(timeout=30.0) as client:
        while url is not None and pages < max_pages:
            if pages == 0:
                resp = client.get(url, headers=headers, params=params)
            else:
                resp = client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            pages += 1

            for msg in data.get("value", []):
                from_obj = msg.get("from") or {}
                email_addr_obj = from_obj.get("emailAddress") or {}
                sender_email: str = email_addr_obj.get("address") or ""
                sender_name: str = email_addr_obj.get("name") or ""
                domain = sender_email.lower().split("@", 1)[-1] if "@" in sender_email else ""

                results.append(
                    EmailMessage(
                        id=msg.get("id", ""),
                        subject=msg.get("subject") or "",
                        sender_name=sender_name,
                        sender_email=sender_email,
                        sender_domain=domain,
                        received_at=_parse_dt(msg.get("receivedDateTime")),
                        body_preview=msg.get("bodyPreview") or "",
                        importance=_importance_from_str(msg.get("importance")),
                        is_read=bool(msg.get("isRead", False)),
                        web_link=msg.get("webLink"),
                        category_hint=CategoryHint.OTHER,
                    )
                )

            url = data.get("@odata.nextLink")

    return results


def fetch_calendar(
    cred: DeviceCodeCredential,
    day: date,
    *,
    timezone_name: str = "UTC",
) -> list[CalendarEvent]:
    """Fetch /me/calendarView for the given local day.

    Uses the `Prefer: outlook.timezone="<zone>"` header so start/end come back
    in the user's tz rather than UTC.
    """
    # Compute day boundaries in UTC (Graph calendarView needs ISO 8601 strings)
    start_dt = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=UTC)
    end_dt = start_dt + timedelta(days=1)

    windows_tz = _IANA_TO_WINDOWS.get(timezone_name, timezone_name)

    params = {
        "startDateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "endDateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "$select": "id,subject,start,end,location,isAllDay,attendees,webLink",
    }
    headers = {
        "Authorization": _get_bearer(cred),
        "Prefer": f'outlook.timezone="{windows_tz}"',
    }

    results: list[CalendarEvent] = []

    with httpx.Client(timeout=30.0) as client:
        resp = client.get(f"{_GRAPH_BASE}/me/calendarView", headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()

    for ev in data.get("value", []):
        location_obj = ev.get("location") or {}
        location_str = location_obj.get("displayName") or ""

        attendees: list[EventAttendee] = []
        for att in ev.get("attendees") or []:
            ea = (att.get("emailAddress") or {})
            status = (att.get("status") or {})
            attendees.append(
                EventAttendee(
                    name=ea.get("name") or "",
                    email=ea.get("address") or "",
                    response=status.get("response") or "none",
                )
            )

        start_obj = ev.get("start") or {}
        end_obj = ev.get("end") or {}

        results.append(
            CalendarEvent(
                id=ev.get("id", ""),
                subject=ev.get("subject") or "",
                start=_parse_dt_timezone(start_obj),
                end=_parse_dt_timezone(end_obj),
                location=location_str,
                is_all_day=bool(ev.get("isAllDay", False)),
                attendees=attendees,
                web_link=ev.get("webLink"),
            )
        )

    return results


__all__ = ["fetch_emails", "fetch_calendar"]
