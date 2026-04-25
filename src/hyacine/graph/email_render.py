"""Modern HTML email shell for the daily digest.

Wraps the LLM-produced markdown body in HyacineAI's design language:
pansy logo header, hero title, color-bar section titles, three-segment
footer with model/date metadata. The shell uses inline styles
throughout so it survives Gmail web, Apple Mail, iOS Mail, and most
modern clients. Outlook desktop ignores SVG and gradients but the
layout still reads correctly because every block is a ``<table>`` with
explicit widths.
"""
from __future__ import annotations

import html as _html
import re
from datetime import datetime


def _esc(s: str) -> str:
    """HTML-escape a string we are about to interpolate into a template.

    Header/footer fields (model id, date, weekday, generated_at) flow
    through here because they originate from config or pipeline state —
    a crafted model id ``</span><script>...`` must not punch through
    into the rendered email.
    """
    return _html.escape(s, quote=True)

# Palette — matches hyacine.ai landing page and the design canvas.
_INK = "#1F1631"
_PLUM = "#5A4873"
_PLUM_SOFT = "#857398"
_PAPER = "#FFFCFB"
_PAGE_BG = "#F5F1F8"
_LINE = "#EDE7F2"
_LINE_SOFT = "#F4EFF7"
_ACCENT = "#9A7ECC"
_ACCENT_SOFT = "#C8B4E8"
_PINK = "#F4B6C9"
_PINK_DEEP = "#E88BA8"
_LAVENDER_DEEP = "#9A7ECC"
_SKY_DEEP = "#7BA8D4"
_GOLD_DEEP = "#B8893B"

_SERIF = "'Noto Serif SC','Source Han Serif SC','Songti SC',serif"
_SANS = (
    "-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB',"
    "'Microsoft Yahei',sans-serif"
)
_MONO = "'JetBrains Mono','SF Mono',Menlo,monospace"

# Map LLM section emojis → accent color for the section's left bar.
# The prompts/hyacine.md.template emits these prefixes for each H2.
_EMOJI_ACCENT: dict[str, str] = {
    "🔴": _PINK_DEEP,       # 今日必做 / Must do today
    "🟡": _LAVENDER_DEEP,   # 研究相关 / Research
    "🟢": _SKY_DEEP,        # 行政通知 / Admin
    "⚪": _GOLD_DEEP,       # FYI
    "📅": _SKY_DEEP,        # Calendar
    "🎯": _PINK_DEEP,       # Top focus
    "📬": _LAVENDER_DEEP,   # Generic header (fallback)
}

_PANSY_SVG_22 = (
    '<svg width="22" height="22" viewBox="0 0 40 40" '
    'style="display:block;vertical-align:middle;">'
    '<ellipse cx="20" cy="13" rx="6" ry="7" fill="#E88BA8"/>'
    '<ellipse cx="11" cy="20" rx="7" ry="6" fill="#C8B4E8" '
    'transform="rotate(-30 11 20)"/>'
    '<ellipse cx="29" cy="20" rx="7" ry="6" fill="#9A7ECC" '
    'transform="rotate(30 29 20)"/>'
    '<ellipse cx="14" cy="29" rx="6" ry="6" fill="#B8D4EC" '
    'transform="rotate(-15 14 29)"/>'
    '<ellipse cx="26" cy="29" rx="6" ry="6" fill="#F4B6C9" '
    'transform="rotate(15 26 29)"/>'
    '<circle cx="20" cy="20" r="2.5" fill="#E8C87A"/>'
    "</svg>"
)
_PANSY_SVG_20 = _PANSY_SVG_22.replace(
    'width="22" height="22"', 'width="20" height="20"'
)


def _style_body(html: str) -> str:
    """Inject inline styles matching the modern email design language.

    Operates on bleach-sanitized HTML; tag set is restricted so the
    pattern matches stay simple. Non-greedy ``.*?`` is safe here because
    the cleaned HTML never has nested elements of the same kind.
    """
    # h1 → hero serif title (38px)
    html = re.sub(
        r"<h1>(.*?)</h1>",
        (
            f'<h1 style="font-family:{_SERIF};font-size:38px;font-weight:600;'
            f"letter-spacing:-0.5px;line-height:1.2;color:{_INK};"
            'margin:0 0 14px;">\\1</h1>'
        ),
        html,
        flags=re.DOTALL,
    )

    def _repl_h2(m: re.Match[str]) -> str:
        text = m.group(1).strip()
        color = _ACCENT
        for emoji, c in _EMOJI_ACCENT.items():
            if text.startswith(emoji):
                color = c
                text = text[len(emoji):].lstrip()
                break
        return (
            '<table cellpadding="0" cellspacing="0" border="0" '
            'role="presentation" '
            "style=\"width:100%;border-collapse:collapse;margin:36px 0 14px;"
            f'border-bottom:1px solid {_LINE};">'
            "<tr>"
            f'<td style="width:4px;background:{color};border-radius:2px;'
            'padding:0;font-size:0;line-height:0;">&nbsp;</td>'
            '<td style="width:14px;padding:0;font-size:0;line-height:0;">'
            "&nbsp;</td>"
            f'<td style="font-family:{_SERIF};font-size:22px;font-weight:600;'
            f"letter-spacing:-0.2px;color:{_INK};line-height:1.2;"
            'padding:0 0 12px;vertical-align:middle;">'
            f"{text}"
            "</td>"
            "</tr>"
            "</table>"
        )

    html = re.sub(r"<h2>(.*?)</h2>", _repl_h2, html, flags=re.DOTALL)

    # h3 → smaller serif subhead
    html = re.sub(
        r"<h3>(.*?)</h3>",
        (
            f'<h3 style="font-family:{_SERIF};font-size:16px;font-weight:600;'
            f'color:{_INK};line-height:1.4;margin:20px 0 8px;">\\1</h3>'
        ),
        html,
        flags=re.DOTALL,
    )

    # blockquote → mono stats line on a soft tint (matches hero stats row)
    html = re.sub(
        r"<blockquote>\s*(.*?)\s*</blockquote>",
        (
            f'<div style="font-family:{_MONO};font-size:13px;color:{_PLUM_SOFT};'
            "letter-spacing:0.3px;line-height:1.7;margin:0 0 28px;"
            f"padding:14px 18px;background:{_PAGE_BG};border-radius:8px;"
            f'border-left:3px solid {_ACCENT_SOFT};">\\1</div>'
        ),
        html,
        flags=re.DOTALL,
    )

    # hr → hairline gradient divider
    html = re.sub(
        r"<hr\s*/?>",
        (
            f'<div style="height:1px;background:{_ACCENT_SOFT};'
            "background-image:linear-gradient(90deg,transparent 0%,"
            "#C8B4E8 30%,#F4B6C9 65%,transparent 100%);margin:32px 0;"
            'font-size:0;line-height:0;">&nbsp;</div>'
        ),
        html,
    )

    # paragraphs
    html = re.sub(
        r"<p>(.*?)</p>",
        (
            f'<p style="font-size:14px;color:{_PLUM};line-height:1.7;'
            'margin:0 0 14px;">\\1</p>'
        ),
        html,
        flags=re.DOTALL,
    )

    # ul → bare list with item left-bar; ol keeps the numerals
    html = html.replace(
        "<ul>",
        '<ul style="list-style:none;padding:0;margin:0 0 18px;">',
    )
    html = html.replace(
        "<ol>",
        f'<ol style="list-style:decimal;padding-left:24px;margin:0 0 18px;color:{_PLUM};">',
    )
    # Style on opening tag only — non-greedy ``<li>(.*?)</li>`` would
    # corrupt nested lists by ending the outer match at the first inner
    # ``</li>``. ``str.replace`` is safe regardless of nesting.
    html = html.replace(
        "<li>",
        (
            f'<li style="font-size:14px;color:{_INK};line-height:1.7;'
            "padding:10px 0 10px 16px;border-left:2px solid "
            f'{_LINE};margin:0 0 8px;">'
        ),
    )

    # tables (calendar block, etc.)
    html = html.replace(
        "<table>",
        (
            '<table cellpadding="0" cellspacing="0" border="0" '
            'role="presentation" '
            'style="width:100%;border-collapse:collapse;margin:0 0 18px;'
            'font-size:13px;">'
        ),
    )
    html = re.sub(
        r"<th>(.*?)</th>",
        (
            f'<th style="text-align:left;padding:10px 12px;'
            f"border-bottom:1px solid {_LINE};font-family:{_MONO};"
            f"font-size:11px;letter-spacing:1.5px;color:{_PLUM_SOFT};"
            'font-weight:700;text-transform:uppercase;">\\1</th>'
        ),
        html,
        flags=re.DOTALL,
    )
    html = re.sub(
        r"<td>(.*?)</td>",
        (
            f'<td style="padding:10px 12px;border-bottom:1px solid {_LINE_SOFT};'
            f'color:{_PLUM};vertical-align:top;">\\1</td>'
        ),
        html,
        flags=re.DOTALL,
    )

    # strong / em
    html = re.sub(
        r"<strong>(.*?)</strong>",
        f'<strong style="color:{_INK};font-weight:600;">\\1</strong>',
        html,
        flags=re.DOTALL,
    )
    html = re.sub(
        r"<em>(.*?)</em>",
        f'<em style="color:{_PLUM};font-style:italic;">\\1</em>',
        html,
        flags=re.DOTALL,
    )

    # Inject style onto every ``<a ...>`` opening tag, preserving
    # ``href`` plus any other attributes bleach may have left intact
    # (``title`` in particular). Matching only the opening tag keeps us
    # robust against the full anchor body being a multi-line markdown
    # phrase or containing nested elements.
    html = re.sub(
        r"<a ([^>]*)>",
        (
            f'<a \\1 style="color:{_ACCENT};text-decoration:none;'
            f'border-bottom:1px solid {_ACCENT_SOFT};">'
        ),
        html,
    )

    # inline code
    html = re.sub(
        r"<code>(.*?)</code>",
        (
            f'<code style="font-family:{_MONO};font-size:12px;'
            f"background:{_PAGE_BG};padding:2px 6px;border-radius:4px;"
            f'color:{_INK};">\\1</code>'
        ),
        html,
        flags=re.DOTALL,
    )

    return html


def _render_header(date: str, weekday: str) -> str:
    date_str = _esc(date or datetime.now().strftime("%Y-%m-%d"))
    weekday_str = _esc(weekday)
    suffix = f" · {weekday_str}" if weekday_str else ""
    return (
        '<tr><td style="padding:40px 56px 28px;">'
        '<table cellpadding="0" cellspacing="0" border="0" role="presentation" '
        'style="width:100%;border-collapse:collapse;"><tr>'
        '<td valign="middle" style="padding:0;">'
        '<table cellpadding="0" cellspacing="0" border="0" role="presentation" '
        'style="border-collapse:collapse;"><tr>'
        '<td valign="middle" style="padding:0 10px 0 0;">'
        f"{_PANSY_SVG_22}"
        "</td>"
        f'<td valign="middle" style="font-family:{_SERIF};font-size:18px;'
        f'font-weight:600;letter-spacing:0.2px;color:{_INK};padding:0;">'
        "HyacineAI"
        "</td></tr></table></td>"
        f'<td valign="middle" align="right" style="font-family:{_MONO};'
        f'font-size:12px;color:{_PLUM_SOFT};letter-spacing:0.5px;padding:0;">'
        f"{date_str}{suffix}"
        "</td></tr></table>"
        '<div style="margin-top:24px;height:1px;background:#C8B4E8;'
        "background-image:linear-gradient(90deg,transparent 0%,#C8B4E8 30%,"
        '#F4B6C9 65%,transparent 100%);font-size:0;line-height:0;">&nbsp;</div>'
        "</td></tr>"
    )


def _render_footer(model: str, date: str, generated_at: str) -> str:
    date_str = _esc(date or datetime.now().strftime("%Y-%m-%d"))
    time_str = _esc(generated_at or datetime.now().strftime("%H:%M"))
    model_esc = _esc(model)
    if model_esc:
        model_chip = (
            f'<span style="color:{_ACCENT};font-weight:600;">{model_esc}</span>'
        )
    else:
        model_chip = (
            f'<span style="color:{_PLUM};">your local LLM</span>'
        )
    return (
        '<tr><td style="padding:48px 56px 56px;'
        f"border-top:1px solid {_LINE};background:#FFF4F8;"
        'background-image:linear-gradient(180deg,transparent 0%,#FFF4F8 100%);">'
        # segment 1: logo + signature
        '<table cellpadding="0" cellspacing="0" border="0" role="presentation" '
        'style="border-collapse:collapse;margin-bottom:18px;"><tr>'
        '<td valign="middle" style="padding:0 12px 0 0;">'
        f"{_PANSY_SVG_20}"
        "</td>"
        f'<td valign="middle" style="padding:0 12px 0 0;font-family:{_SERIF};'
        f'font-size:15px;font-weight:600;color:{_INK};white-space:nowrap;">'
        "HyacineAI</td>"
        f'<td valign="middle" style="font-family:{_SERIF};font-size:14px;'
        f'color:{_PLUM_SOFT};font-style:italic;">'
        "—— 你的清晨第一封邮件，值得是这一封。"
        "</td></tr></table>"
        # segment 2: links
        f'<div style="margin-bottom:22px;font-size:13px;color:{_PLUM};">'
        f'<a href="https://hyacine.ai" style="color:{_ACCENT};'
        f"text-decoration:none;border-bottom:1px solid {_ACCENT_SOFT};"
        'margin-right:24px;">hyacine.ai</a>'
        # Source line keeps both the canonical URL and the display
        # text on a single physical line so scripts/scrub_check
        # treats it as the canonical public project URL.
        f'<a href="https://github.com/lushuyu/Hyacine" style="color:{_ACCENT};text-decoration:none;border-bottom:1px solid {_ACCENT_SOFT};">GitHub · lushuyu/Hyacine</a>'
        "</div>"
        # segment 3: generated by
        f'<div style="font-family:{_MONO};font-size:11px;color:{_PLUM_SOFT};'
        'letter-spacing:0.4px;line-height:1.7;">'
        f"Generated by HyacineAI · powered by {model_chip} · "
        f"{date_str} {time_str}<br/>"
        "本邮件由你本机自动生成 · 凭据与正文从未离开你的设备"
        "</div></td></tr>"
    )


# Map ``hyacine.config.YamlConfig.language`` codes → BCP-47 language
# tags for the document's ``<html lang>`` attribute. Anything we don't
# recognise falls back to ``en`` so screen readers and client-side
# heuristics get a sensible default rather than a stale ``zh-CN``.
_LANG_TAGS: dict[str, str] = {
    "en": "en",
    "zh-cn": "zh-CN",
    "zh-tw": "zh-TW",
    "zh": "zh-CN",
    "ja": "ja",
}


def _bcp47(language: str) -> str:
    if not language:
        return "en"
    return _LANG_TAGS.get(language.lower(), language)


def render_modern_email_html(
    body_html: str,
    *,
    model: str = "",
    date: str = "",
    weekday: str = "",
    generated_at: str = "",
    language: str = "",
) -> str:
    """Wrap a sanitized HTML body in the HyacineAI modern email shell.

    ``body_html`` should already be bleach-cleaned. ``language`` accepts
    the same codes as ``YamlConfig.language`` (``en``, ``zh-CN``,
    ``zh-TW``, ``ja``) and is mapped to a BCP-47 tag for the
    document's ``<html lang>`` attribute — defaulting to ``en`` so the
    metadata reflects the actual digest language rather than a stale
    hardcoded value. Footer fields default to empty strings — when
    omitted the shell falls back to "your local LLM" and the current
    local date/time.
    """
    styled_body = _style_body(body_html)
    header = _render_header(date, weekday)
    footer = _render_footer(model, date, generated_at)
    lang_tag = _bcp47(language)
    return (
        f'<!doctype html><html lang="{_esc(lang_tag)}"><head>'
        '<meta charset="utf-8"/>'
        '<meta name="viewport" content="width=device-width,initial-scale=1"/>'
        '<meta name="x-apple-disable-message-reformatting"/>'
        "<title>HyacineAI · 每日晨报</title>"
        "</head>"
        f'<body style="margin:0;padding:0;background:{_PAGE_BG};'
        f"font-family:{_SANS};color:{_INK};line-height:1.6;"
        '-webkit-text-size-adjust:100%;">'
        # Outer page-bg wrapper — Outlook honours bgcolor on tables.
        '<table cellpadding="0" cellspacing="0" border="0" role="presentation" '
        f'width="100%" bgcolor="{_PAGE_BG}" '
        f'style="width:100%;background:{_PAGE_BG};border-collapse:collapse;">'
        '<tr><td align="center" style="padding:24px 0;">'
        # Inner 800px card.
        '<table cellpadding="0" cellspacing="0" border="0" role="presentation" '
        'align="center" width="800" '
        "style=\"max-width:800px;width:100%;margin:0 auto;"
        f"background:{_PAPER};border-collapse:collapse;"
        "background-image:radial-gradient(ellipse at 50% -10%,"
        "rgba(244,182,201,0.13) 0%,transparent 40%),"
        "radial-gradient(ellipse at 100% 0%,rgba(200,180,232,0.13) 0%,"
        'transparent 35%);">'
        "<tbody>"
        f"{header}"
        '<tr><td style="padding:8px 56px 24px;">'
        f"{styled_body}"
        "</td></tr>"
        f"{footer}"
        "</tbody></table>"
        "</td></tr></table>"
        "</body></html>"
    )


def render_email_fragment(body_html: str) -> str:
    """Style a sanitized HTML body with the modern email aesthetic.

    Returns the styled markup *without* the ``<!doctype html>`` /
    ``<body>`` wrapper. Use this when embedding the rendered digest
    inside another HTML page (e.g. the FastAPI run-detail view) where
    a full document would nest inside a ``<div>`` and confuse the
    surrounding template.
    """
    return _style_body(body_html)


__all__ = ["render_modern_email_html", "render_email_fragment"]
