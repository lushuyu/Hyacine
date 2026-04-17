"""Send the briefing via POST /me/sendMail."""
from __future__ import annotations

import re
import uuid

import bleach
import httpx
import markdown as md_lib
from azure.identity import DeviceCodeCredential

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


def render_html_body(markdown_text: str) -> str:
    """Convert markdown → sanitized HTML suitable for Outlook.

    Pipeline: markdown.markdown(extensions=["extra", "sane_lists", "tables"])
    then bleach.clean with an allowlist of tags/attrs that Outlook renders well.
    """
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


def send_briefing_email(
    cred: DeviceCodeCredential,
    recipient: str,
    subject: str,
    markdown_body: str,
    *,
    save_to_sent_items: bool = True,
) -> str:
    """POST /me/sendMail with HTML body. Returns a logical message identifier.

    Note: /me/sendMail returns 202 with no body; the returned id is either the
    Graph request-id header or a synthetic one for logging — do NOT treat it
    as a retrievable message id.
    """
    html_content = render_html_body(markdown_body)

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


__all__ = ["send_briefing_email", "render_html_body"]
