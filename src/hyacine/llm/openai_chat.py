"""Backend for ``api_format = "openai_chat"``.

Speaks the `/v1/chat/completions`` dialect: OpenAI proper, Azure, Groq,
DeepSeek's OAI-style endpoint, Together, LM Studio and Ollama (both of
which mirror the OpenAI API on their local servers).

Auth convention: ``Authorization: Bearer <key>``. Azure's native header
is ``api-key`` but most Azure-proxied front-ends also accept Bearer; we
don't ship an Azure preset in Phase 1 so we skip the special case.
Hostnames running an unauthenticated local model (Ollama, LM Studio)
can pass an empty string as the key — the header is omitted in that
case.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx


class OpenAiChatError(RuntimeError):
    """Raised when an openai_chat call can't be completed or is refused."""


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
    """POST to ``<base_url>/chat/completions`` and return the message text.

    ``base_url`` is the host + ``/v1`` segment; relay URLs like
    ``https://api.groq.com/openai/v1`` therefore point at the Chat
    Completions endpoint at ``…/v1/chat/completions`` when we append.
    """
    if not system_prompt_path.exists():
        raise OpenAiChatError(
            f"System prompt file not found: {system_prompt_path}"
        )
    system_prompt = system_prompt_path.read_text(encoding="utf-8")

    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"content-type": "application/json"}
    if api_key.strip():
        headers["authorization"] = f"Bearer {api_key.strip()}"

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"{user_message}\n\n"
                    "--- JSON payload below ---\n"
                    f"{json_input}"
                ),
            },
        ],
        # Modest cap — Hyacine summaries fit comfortably here.
        "max_tokens": 4096,
    }

    try:
        r = httpx.post(url, headers=headers, json=body, timeout=timeout_seconds)
    except httpx.HTTPError as e:
        raise OpenAiChatError(f"network error: {e}") from e

    if r.status_code != 200:
        snippet = r.text[:500]
        raise OpenAiChatError(f"HTTP {r.status_code}: {snippet}")

    try:
        data = r.json()
    except json.JSONDecodeError as e:
        raise OpenAiChatError(f"non-JSON response: {e}") from e

    choices = data.get("choices") or []
    if not choices:
        raise OpenAiChatError(f"no choices in response; keys={list(data.keys())}")
    first = choices[0]
    if not isinstance(first, dict):
        raise OpenAiChatError("malformed choice entry")

    msg = first.get("message") or {}
    text = msg.get("content")
    if isinstance(text, str) and text.strip():
        return text
    # Some tools-oriented endpoints return content as a list of segment dicts.
    if isinstance(text, list):
        parts = [
            seg.get("text", "")
            for seg in text
            if isinstance(seg, dict) and seg.get("type") in ("text", "output_text")
        ]
        joined = "".join(parts).strip()
        if joined:
            return joined
    raise OpenAiChatError("response had no text content")


__all__ = ["OpenAiChatError", "summarize"]
