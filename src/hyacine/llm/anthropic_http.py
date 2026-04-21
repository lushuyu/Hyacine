"""Backend for ``api_format = "anthropic_http"``.

Covers anyone speaking Anthropic's ``/v1/messages`` contract: the Console
API itself and every relay (DeepSeek, Kimi, Zhipu, OpenRouter, AiHubMix,
Bedrock-via-proxy, …) that exposes an Anthropic-compatible path under a
different host.

Auth: ``x-api-key: <key>`` — the only header every relay we've tested
actually accepts. A Bearer fallback could be added if we run into a relay
that insists, but Anthropic's spec says x-api-key.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx


class AnthropicHttpError(RuntimeError):
    """Raised when an anthropic_http call can't be completed or is refused."""


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

    url = base_url.rstrip("/") + "/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": 4096,
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

    # Anthropic returns {content: [{type: "text", text: "..."}], ...}. Some
    # relays emit a single string in content instead — handle both.
    content = data.get("content")
    if isinstance(content, str):
        return content
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
        f"unexpected response shape; keys={list(data.keys())}"
    )


__all__ = ["AnthropicHttpError", "summarize"]
