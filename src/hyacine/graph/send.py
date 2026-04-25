"""Send a hyacine report via POST /me/sendMail."""
from __future__ import annotations

import re
import uuid

import bleach
import httpx
import markdown as md_lib
from azure.identity import DeviceCodeCredential

from hyacine.graph.email_render import (
    render_email_fragment,
    render_modern_email_html,
)

# Tags whose entire content (not just the tag itself) must be removed.
_DANGEROUS_TAG_RE = re.compile(
    r"<(script|style|iframe|object|embed|form|input|button|select|textarea|link|meta|base)"
    r"[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"

_ALLOWED_TAGS = [
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li",
    "strong", "em",
    "a", "blockquote", "code", "pre", "hr", "br",
    "table", "thead", "tbody", "tr", "th", "td",
    "span", "div", "img",
]

_ALLOWED_ATTRS: dict[str, list[str]] = {
    "a": ["href", "title"],
    "img": ["src", "alt"],
}

_ALLOWED_PROTOCOLS = ["https", "http", "mailto"]


def _markdown_to_safe_html(markdown_text: str) -> str:
    """Markdown → bleach-sanitized HTML (no styling, no shell)."""
    raw_html = md_lib.markdown(
        markdown_text,
        extensions=["extra", "sane_lists", "tables"],
    )
    # Pre-strip dangerous tags *including their content* before bleach runs.
    # bleach strip=True would leave the inner text of <script>alert(1)</script>
    # as plain text; we must remove it entirely.
    pre_cleaned = _DANGEROUS_TAG_RE.sub("", raw_html)
    return bleach.clean(
        pre_cleaned,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )


def render_html_body(
    markdown_text: str,
    *,
    model: str = "",
    date: str = "",
    weekday: str = "",
    generated_at: str = "",
) -> str:
    """Convert markdown → modern HyacineAI email HTML (sanitized).

    Pipeline: markdown → bleach allowlist → ``render_modern_email_html``
    (pansy-logo header, hero, color-bar section titles, three-segment
    footer with model/date metadata). Returns a full HTML document
    suitable for ``/me/sendMail``; for embedding the same content
    inside another page use :func:`render_html_fragment`.
    """
    cleaned = _markdown_to_safe_html(markdown_text)
    return render_modern_email_html(
        cleaned,
        model=model,
        date=date,
        weekday=weekday,
        generated_at=generated_at,
    )


def render_html_fragment(markdown_text: str) -> str:
    """Convert markdown → styled body fragment (no doctype/html wrapper).

    Same sanitisation + design language as :func:`render_html_body`,
    but skips the email shell so the result can be embedded inside an
    existing page (e.g. the FastAPI run-detail view) without nesting a
    full document inside a ``<div>``.
    """
    cleaned = _markdown_to_safe_html(markdown_text)
    return render_email_fragment(cleaned)


def send_email(
    cred: DeviceCodeCredential,
    recipient: str,
    subject: str,
    markdown_body: str,
    *,
    save_to_sent_items: bool = True,
    model: str = "",
    date: str = "",
    weekday: str = "",
    generated_at: str = "",
) -> str:
    """POST /me/sendMail with HTML body. Returns a logical message identifier.

    Note: /me/sendMail returns 202 with no body; the returned id is either the
    Graph request-id header or a synthetic one for logging — do NOT treat it
    as a retrievable message id.

    ``model`` / ``date`` / ``weekday`` / ``generated_at`` are forwarded to
    :func:`render_html_body` so the modern email footer can show the
    provider/model and the local time the digest was generated. All four
    are optional; the shell falls back to today's date and a generic
    "your local LLM" chip when missing.
    """
    html_content = render_html_body(
        markdown_body,
        model=model,
        date=date,
        weekday=weekday,
        generated_at=generated_at,
    )

    token = cred.get_token("https://graph.microsoft.com/.default")
    headers = {
        "Authorization": f"Bearer {token.token}",
        "Content-Type": "application/json",
    }

    payload = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": html_content,
            },
            "toRecipients": [
                {"emailAddress": {"address": recipient}},
            ],
        },
        "saveToSentItems": save_to_sent_items,
    }

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{_GRAPH_BASE}/me/sendMail",
            headers=headers,
            json=payload,
        )

    if not resp.is_success:
        raise RuntimeError(
            f"sendMail failed {resp.status_code}: {resp.text}"
        )

    request_id = resp.headers.get("request-id") or resp.headers.get("x-ms-request-id")
    return request_id if request_id else f"sendmail-{uuid.uuid4()}"


__all__ = ["send_email", "render_html_body"]
