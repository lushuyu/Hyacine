"""Backend for ``api_format = "anthropic_http"``.

Covers anyone speaking Anthropic's ``/v1/messages`` contract: the Console
API itself and every relay (DeepSeek, Kimi, Zhipu, OpenRouter, AiHubMix,
Bedrock-via-proxy, …) that exposes an Anthropic-compatible path under a
different host.

Auth: ``x-api-key: <key>`` — the only header every relay we've tested
actually accepts. A Bearer fallback could be added if we run into a relay
that insists, but Anthropic's spec says x-api-key.

First-party vs relay: relays only implement the core of the contract
(DeepSeek, for one, rejects ``max_tokens`` above 8192), so the larger output
budget, ``output_config.effort`` and the server-side refusal fallback are
only sent when the host is ``api.anthropic.com`` — and the last two only for
current-generation models that accept them.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx

_FIRST_PARTY_HOST = "api.anthropic.com"

# Thinking is always on for current Claude models and its tokens count
# toward max_tokens, so first-party gets room for thinking plus a long zh-CN
# digest while staying small enough for a non-streaming request. Relays keep
# the conservative cap they have always accepted.
_FIRST_PARTY_MAX_TOKENS = 16000
_RELAY_MAX_TOKENS = 4096

# Model id prefixes that accept output_config.effort and `fallbacks:
# "default"`. Older models (claude-haiku-4-5, …) reject effort with a 400.
_EFFORT_MODEL_PREFIXES = ("claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5")
_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
# Opus 5.5 defaults to "medium"; the digest is worth the extra thinking.
_DEFAULT_EFFORT = "high"
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicHttpError(RuntimeError):
    """Raised when an anthropic_http call can't be completed or is refused."""


def _resolve_effort() -> str:
    """Return ``HYACINE_CLAUDE_EFFORT`` (validated) or the default."""
    raw = os.environ.get("HYACINE_CLAUDE_EFFORT", "").strip().lower()
    if not raw:
        return _DEFAULT_EFFORT
    if raw not in _EFFORT_LEVELS:
        raise AnthropicHttpError(
            f"HYACINE_CLAUDE_EFFORT={raw!r} is not one of "
            f"{', '.join(_EFFORT_LEVELS)}"
        )
    return raw


def summarize(
    json_input: str,
    system_prompt_path: Path,
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout_seconds: int = 300,
    user_message: str = "Generate the daily report from the JSON on stdin.",
) -> str:
    """Send the daily-briefing request and return the assistant text.

    ``base_url`` is the host + base path, without a trailing ``/v1/messages``
    — we append that here. So Anthropic's own service lives at
    ``https://api.anthropic.com`` and a DeepSeek relay at
    ``https://api.deepseek.com/anthropic``.
    """
    if not system_prompt_path.exists():
        raise AnthropicHttpError(
            f"System prompt file not found: {system_prompt_path}"
        )
    system_prompt = system_prompt_path.read_text(encoding="utf-8")

    first_party = urlparse(base_url).hostname == _FIRST_PARTY_HOST

    url = base_url.rstrip("/") + "/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body: dict[str, object] = {
        "model": model,
        "max_tokens": _FIRST_PARTY_MAX_TOKENS if first_party else _RELAY_MAX_TOKENS,
        "system": system_prompt,
        "messages": [
            {
                "role": "user",
                "content": (
                    f"{user_message}\n\n"
                    "--- JSON payload below ---\n"
                    f"{json_input}"
                ),
            },
        ],
    }
    if first_party and model.startswith(_EFFORT_MODEL_PREFIXES):
        body["output_config"] = {"effort": _resolve_effort()}
        # On a classifier refusal the API re-runs the request on Anthropic's
        # recommended fallback model inside the same call.
        headers["anthropic-beta"] = _FALLBACK_BETA
        body["fallbacks"] = "default"

    try:
        r = httpx.post(url, headers=headers, json=body, timeout=timeout_seconds)
    except httpx.HTTPError as e:
        raise AnthropicHttpError(f"network error: {e}") from e

    if r.status_code != 200:
        snippet = r.text[:500]
        raise AnthropicHttpError(f"HTTP {r.status_code}: {snippet}")

    try:
        data = r.json()
    except json.JSONDecodeError as e:
        raise AnthropicHttpError(f"non-JSON response: {e}") from e

    # Refusals arrive as HTTP 200. With fallbacks on, this means the fallback
    # model declined too. Relays (and older fixtures) may omit stop_reason.
    stop = data.get("stop_reason")
    if stop == "refusal":
        details = data.get("stop_details")
        if not isinstance(details, dict):
            details = {}
        raise AnthropicHttpError(
            "model refused the request "
            f"(category={details.get('category')!r}): "
            f"{details.get('explanation') or 'no explanation given'}"
        )
    if stop in ("max_tokens", "model_context_window_exceeded"):
        raise AnthropicHttpError(
            f"output truncated (stop_reason={stop}); the digest would be incomplete"
        )

    # Anthropic returns {content: [{type: "text", text: "..."}], ...}. Some
    # relays emit a single string in content instead — handle both. Only text
    # blocks are kept: thinking blocks lead current-model responses, and a
    # fallback block marks where a fallback model took over (non-streaming
    # responses omit the declined partial, so every text block is the answer).
    content = data.get("content")
    if isinstance(content, str):
        if content.strip():
            return content.strip()
        raise AnthropicHttpError("response had empty text content")
    if isinstance(content, list):
        parts = [
            c.get("text", "")
            for c in content
            if isinstance(c, dict) and c.get("type") == "text"
        ]
        text = "".join(parts).strip()
        if text:
            return text
        raise AnthropicHttpError(
            f"response had no text content (stop_reason={stop!r})"
        )
    raise AnthropicHttpError(
        f"unexpected response shape; keys={list(data.keys())}"
    )


__all__ = ["AnthropicHttpError", "summarize"]
