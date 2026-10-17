"""Pull messages + today's calendar from Microsoft Graph."""
from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from azure.core.credentials import TokenCredential

from hyacine.graph._http import raise_for_graph_status, request_with_retry
from hyacine.models import CalendarEvent, CategoryHint, EmailMessage, EventAttendee, Importance

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# /me/messages spans the whole mailbox, not just the inbox. Messages in
# these well-known folders are the user's own outgoing mail, drafts or
# trash/spam — never "mail received today" — so they are skipped.
_EXCLUDED_FOLDERS = ("sentitems", "drafts", "deleteditems", "junkemail", "outbox")

# Hyacine's own digest ("Hyacine · YYYY-MM-DD", see pipeline/run.py) and
# the desktop preview (" (preview)" suffix). Skipped wherever it lands so
# yesterday's digest is not summarised into today's.
_OWN_DIGEST_SUBJECT_RE = re.compile(r"^Hyacine · \d{4}-\d{2}-\d{2}( \(preview\))?$")

_CALENDAR_PAGE_SIZE = 100
_CALENDAR_MAX_PAGES = 5

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


class FetchedEmails(list[EmailMessage]):
    """The list :func:`fetch_emails` returns, plus a ``page_cap_hit`` flag.

    ``page_cap_hit`` is True when ``max_pages`` ended the walk with more
    mail pending, i.e. older mail in the window was never fetched. A slice
    is a plain ``list``, so read the flag before slicing.
    """

    page_cap_hit: bool = False


def _get_bearer(cred: TokenCredential) -> str:
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


def _parse_dt_timezone(dt_tz: dict[str, Any], local_tz: tzinfo) -> datetime:
    """Parse a Graph DateTimeTimeZone object {dateTime, timeZone}.

    ``dateTime`` is a naive wall-clock time in the zone named by
    ``timeZone``: the zone requested via ``Prefer: outlook.timezone``
    (passed here as ``local_tz``), or ``"UTC"`` when Graph did not apply
    the header. Labelling a Singapore wall-clock time as UTC would shift
    the meeting by 8h, so naive values get ``local_tz`` unless the
    payload says UTC or names no zone.
    """
    raw = dt_tz.get("dateTime", "")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        dt = datetime.now(tz=UTC)
    if dt.tzinfo is None:
        zone = (dt_tz.get("timeZone") or "").strip().upper()
        dt = dt.replace(tzinfo=UTC if zone in ("", "UTC") else local_tz)
    return dt


def _resolve_excluded_folder_ids(client: httpx.Client, headers: dict[str, str]) -> set[str]:
    """Best-effort ids of the well-known folders in ``_EXCLUDED_FOLDERS``.

    A failed lookup is logged and skipped: it only means that folder's
    messages are not filtered out, which must never fail the run.
    """
    ids: set[str] = set()
    for name in _EXCLUDED_FOLDERS:
        try:
            resp = request_with_retry(
                client,
                "GET",
                f"{_GRAPH_BASE}/me/mailFolders/{name}",
                headers=headers,
                params={"$select": "id"},
            )
            raise_for_graph_status(resp)
            folder_id = resp.json().get("id")
        except Exception as exc:  # noqa: BLE001 — best-effort, see docstring
            logger.warning("Could not resolve mail folder %r; not excluding it: %s", name, exc)
            continue
        if folder_id:
            ids.add(folder_id)
    return ids


def fetch_emails(
    cred: TokenCredential,
    since: datetime,
    until: datetime,
    *,
    top: int = 100,
    max_pages: int = 10,
) -> list[EmailMessage]:
    """Fetch /me/messages in [since, until] using $filter on receivedDateTime.

    Uses $select to trim the payload, $orderby receivedDateTime desc, $top=100,
    and walks @odata.nextLink up to max_pages (logging a warning when the cap
    cuts the window short — the oldest mail in it is then left out). The
    result is a :class:`FetchedEmails` whose ``page_cap_hit`` records that.

    /me/messages covers every folder, so messages in Sent Items, Drafts,
    Deleted Items, Junk and Outbox are skipped, as is Hyacine's own digest.

    Populates sender_domain (lowercased) and leaves category_hint as OTHER —
    that's the rules module's job.
    """
    since_iso = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    until_iso = until.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "$filter": f"receivedDateTime ge {since_iso} and receivedDateTime lt {until_iso}",
        "$orderby": "receivedDateTime desc",
        "$top": str(top),
        "$select": (
            "id,subject,from,receivedDateTime,bodyPreview,importance,isRead,webLink,"
            "parentFolderId"
        ),
    }

    headers = {"Authorization": _get_bearer(cred)}
    url: str | None = f"{_GRAPH_BASE}/me/messages"
    results = FetchedEmails()
    pages = 0
    seen = 0

    with httpx.Client(timeout=30.0) as client:
        excluded_folder_ids = _resolve_excluded_folder_ids(client, headers)

        while url is not None and pages < max_pages:
            if pages == 0:
                resp = request_with_retry(client, "GET", url, headers=headers, params=params)
            else:
                resp = request_with_retry(client, "GET", url, headers=headers)
            raise_for_graph_status(resp)
            data = resp.json()
            pages += 1

            for msg in data.get("value", []):
                seen += 1
                if msg.get("parentFolderId") in excluded_folder_ids:
                    continue
                subject = msg.get("subject") or ""
                if _OWN_DIGEST_SUBJECT_RE.match(subject):
                    continue

                from_obj = msg.get("from") or {}
                email_addr_obj = from_obj.get("emailAddress") or {}
                sender_email: str = email_addr_obj.get("address") or ""
                sender_name: str = email_addr_obj.get("name") or ""
                domain = sender_email.lower().split("@", 1)[-1] if "@" in sender_email else ""

                results.append(
                    EmailMessage(
                        id=msg.get("id", ""),
                        subject=subject,
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

    if url is not None:
        logger.warning(
            "fetch_emails hit the %d-page cap with more mail pending; kept %d of %d "
            "messages fetched for %s..%s — older mail in this window is not included",
            max_pages, len(results), seen, since_iso, until_iso,
        )
    results.page_cap_hit = url is not None

    return results


def fetch_calendar(
    cred: TokenCredential,
    day: date,
    *,
    timezone_name: str = "UTC",
) -> list[CalendarEvent]:
    """Fetch /me/calendarView for ``day`` as a local day in ``timezone_name``.

    The window is local midnight to the next local midnight, sent as
    explicit UTC instants. The `Prefer: outlook.timezone="<zone>"` header
    makes Graph return each event's start/end as wall-clock time in that
    zone; it does not apply to the window bounds. An unknown zone falls
    back to UTC for the window, the header and the parsed times alike.

    Walks @odata.nextLink (100 events per page, at most 5 pages).
    """
    try:
        local_tz: tzinfo = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Unknown timezone %r; using UTC for the calendar day", timezone_name)
        local_tz, timezone_name = UTC, "UTC"

    # Graph reads offset-less bounds as UTC, so convert the local day
    # explicitly. Next local midnight (not +24h) keeps DST days correct.
    start_dt = datetime.combine(day, time.min, tzinfo=local_tz)
    end_dt = datetime.combine(day + timedelta(days=1), time.min, tzinfo=local_tz)

    windows_tz = _IANA_TO_WINDOWS.get(timezone_name, timezone_name)

    params = {
        "startDateTime": start_dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endDateTime": end_dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "$select": "id,subject,start,end,location,isAllDay,attendees,webLink",
        "$orderby": "start/dateTime",
        "$top": str(_CALENDAR_PAGE_SIZE),
    }
    headers = {
        "Authorization": _get_bearer(cred),
        "Prefer": f'outlook.timezone="{windows_tz}"',
    }

    raw_events: list[dict[str, Any]] = []
    url: str | None = f"{_GRAPH_BASE}/me/calendarView"
    pages = 0

    with httpx.Client(timeout=30.0) as client:
        while url is not None and pages < _CALENDAR_MAX_PAGES:
            # nextLink carries the query string but not headers, so Prefer
            # is re-sent on every page.
            if pages == 0:
                resp = request_with_retry(client, "GET", url, headers=headers, params=params)
            else:
                resp = request_with_retry(client, "GET", url, headers=headers)
            raise_for_graph_status(resp)
            data = resp.json()
            pages += 1
            raw_events.extend(data.get("value", []))
            url = data.get("@odata.nextLink")

    if url is not None:
        logger.warning(
            "fetch_calendar hit the %d-page cap with more events pending; "
            "returning the first %d events of %s",
            _CALENDAR_MAX_PAGES, len(raw_events), day.isoformat(),
        )

    results: list[CalendarEvent] = []

    for ev in raw_events:
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
                start=_parse_dt_timezone(start_obj, local_tz),
                end=_parse_dt_timezone(end_obj, local_tz),
                location=location_str,
                is_all_day=bool(ev.get("isAllDay", False)),
                attendees=attendees,
                web_link=ev.get("webLink"),
            )
        )

    return results


__all__ = ["FetchedEmails", "fetch_emails", "fetch_calendar"]
