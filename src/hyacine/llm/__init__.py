"""LLM dispatch layer.

Callers (the pipeline, IPC handlers, tests) import :func:`summarize` from
here and hand it a :class:`~hyacine.llm.providers.Provider`. The function
routes to the right backend based on ``provider.api_format``.

The split keeps ``hyacine.pipeline.run`` provider-agnostic: adding a new
LLM vendor is a new row in :data:`hyacine.llm.providers.BUILTIN_PRESETS`
plus (if the vendor needs a new wire format) a new sibling module. No
pipeline changes.
"""
from __future__ import annotations

from pathlib import Path

from hyacine.llm import anthropic_http, claude_code, openai_chat
from hyacine.llm.providers import (
    BUILTIN_PRESETS,
    Provider,
    by_id,
    default_provider,
)


class LlmError(RuntimeError):
    """Umbrella for all backend-specific failure modes.

    Each backend raises its own subclass-like RuntimeError
    (ClaudeCodeError / AnthropicHttpError / OpenAiChatError). We don't
    unify them into a class hierarchy because the callers care more about
    the message than the type.
    """


def summarize(
    json_input: str,
    system_prompt_path: Path,
    *,
    provider: Provider,
    api_key: str = "",
    model: str = "",
    timeout_seconds: int = 300,
    user_message: str = "Generate the daily report from the JSON on stdin.",
) -> str:
    """Produce the daily-briefing text for the given provider.

    ``api_key`` is ignored for :attr:`ApiFormat.anthropic_cli` (the CLI
    picks up ``CLAUDE_CODE_OAUTH_TOKEN`` from its own env) and optional
    for local providers like Ollama. For everything else it's required.

    ``model`` falls back to ``provider.default_model`` when empty; callers
    normally forward the user's `llm_model` config.
    """
    effective_model = model or provider.default_model

    if provider.api_format == "anthropic_cli":
        return claude_code.summarize(
            json_input,
            system_prompt_path,
            model=effective_model,
            timeout_seconds=timeout_seconds,
            user_message=user_message,
        )
    if provider.api_format == "anthropic_http":
        if not provider.base_url:
            raise LlmError(f"provider {provider.id!r} missing base_url")
        return anthropic_http.summarize(
            json_input,
            system_prompt_path,
            base_url=provider.base_url,
            api_key=api_key,
            model=effective_model,
            timeout_seconds=timeout_seconds,
            user_message=user_message,
        )
    if provider.api_format == "openai_chat":
        if not provider.base_url:
            raise LlmError(f"provider {provider.id!r} missing base_url")
        return openai_chat.summarize(
            json_input,
            system_prompt_path,
            base_url=provider.base_url,
            api_key=api_key,
            model=effective_model,
            timeout_seconds=timeout_seconds,
            user_message=user_message,
        )
    raise LlmError(f"unknown api_format: {provider.api_format!r}")


__all__ = [
    "BUILTIN_PRESETS",
    "LlmError",
    "Provider",
    "by_id",
    "default_provider",
    "summarize",
]
