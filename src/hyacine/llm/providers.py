"""Provider registry: every LLM backend Hyacine can talk to, in one list.

A *provider* is the glue between "where does traffic go?" and "which wire
format does it speak?". Three formats cover every realistic deployment:

* ``anthropic_cli``  — shell out to the `claude` CLI (Claude Code OAuth token
                       auth). What the existing pipeline has always used.
* ``anthropic_http`` — HTTPS POST to ``/v1/messages`` with ``x-api-key``. Works
                       for Anthropic Console keys *and* every relay that
                       exposes an Anthropic-compatible path (DeepSeek, Kimi,
                       Zhipu GLM, OpenRouter, AiHubMix, …).
* ``openai_chat``    — HTTPS POST to ``/v1/chat/completions``. OpenAI, Azure,
                       Groq, DeepSeek's OpenAI endpoint, local LM Studio and
                       Ollama, etc.

The shape was inspired by farion1231/cc-switch's provider presets — we skip
their per-tool and cost-tracking bits because Hyacine only has one LLM call
site.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ApiFormat = Literal["anthropic_cli", "anthropic_http", "openai_chat"]
Category = Literal[
    "official",       # first-party vendor
    "relay",          # Anthropic-compatible reseller
    "cn_official",    # first-party from a non-US region
    "aggregator",     # multi-model router (OpenRouter, AiHubMix)
    "local",          # self-hosted: Ollama, LM Studio
    "custom",         # user-supplied
]


@dataclass(frozen=True)
class Provider:
    """One row in the provider catalogue.

    A provider is immutable config. The *secret* lives in the OS keychain
    under the slug named by :attr:`secret_slug`; the desktop shell writes it
    once when the user finishes the wizard and never passes the plaintext
    back through the webview.
    """

    id: str
    """Stable identifier (matches the keychain slug by default)."""

    name: str
    """Human-readable label shown in the picker."""

    category: Category

    api_format: ApiFormat

    base_url: str
    """Fully-qualified URL (``http://`` for localhost / ``https://`` otherwise).
    Endpoint suffix (``/v1/messages`` etc.) is appended by the concrete
    backend, so presets only set the host + base path (e.g.
    ``https://api.deepseek.com/anthropic`` or
    ``http://localhost:11434/v1`` for a local Ollama)."""

    default_model: str

    secret_slug: str
    """Keychain slug. Multiple providers can share the same slug if users
    want to reuse e.g. a single Anthropic Console key for both the official
    and a relay endpoint, but by convention we keep them distinct."""

    # Optional / cosmetic
    docs_url: str = ""
    icon: str = ""
    icon_color: str = ""
    notes: str = ""
    models: tuple[str, ...] = field(default_factory=tuple)
    """Known model IDs for this provider — populates the model dropdown.
    Empty tuple means "free-form text input"."""


# ── Built-in presets ───────────────────────────────────────────────────────
# Not exhaustive — we pick one representative per category so the wizard has
# sensible defaults. Users add more via the custom-provider editor.

BUILTIN_PRESETS: tuple[Provider, ...] = (
    Provider(
        id="claude-code-oauth",
        name="Claude (Claude Code OAuth)",
        category="official",
        api_format="anthropic_cli",
        base_url="",                   # CLI handles this
        default_model="sonnet",
        secret_slug="claude-code-oauth",
        docs_url="https://docs.anthropic.com/en/docs/claude-code",
        icon_color="#8b5cf6",
        notes="Uses the `claude` CLI under the hood (same as a normal Claude Code session).",
        models=("sonnet", "opus", "haiku"),
    ),
    Provider(
        id="anthropic-console",
        name="Anthropic Console",
        category="official",
        api_format="anthropic_http",
        base_url="https://api.anthropic.com",
        default_model="claude-sonnet-4-5",
        secret_slug="anthropic-console",
        docs_url="https://console.anthropic.com/settings/keys",
        icon_color="#8b5cf6",
        models=(
            "claude-sonnet-4-5",
            "claude-haiku-4-5",
            "claude-opus-4-5",
        ),
    ),
    Provider(
        id="deepseek-anthropic",
        name="DeepSeek (Anthropic-compatible)",
        category="relay",
        api_format="anthropic_http",
        base_url="https://api.deepseek.com/anthropic",
        default_model="deepseek-chat",
        secret_slug="deepseek-anthropic",
        docs_url="https://platform.deepseek.com/",
        icon_color="#2563eb",
        models=("deepseek-chat", "deepseek-reasoner"),
    ),
    Provider(
        id="kimi-anthropic",
        name="Kimi (Moonshot) Anthropic",
        category="cn_official",
        api_format="anthropic_http",
        base_url="https://api.moonshot.cn/anthropic",
        default_model="kimi-k2-0905-preview",
        secret_slug="kimi-anthropic",
        docs_url="https://platform.moonshot.cn/",
        icon_color="#0ea5e9",
    ),
    Provider(
        id="zhipu-glm-anthropic",
        name="Zhipu GLM (Anthropic-compatible)",
        category="cn_official",
        api_format="anthropic_http",
        base_url="https://open.bigmodel.cn/api/anthropic",
        default_model="glm-4.6",
        secret_slug="zhipu-glm-anthropic",
        docs_url="https://bigmodel.cn/",
        icon_color="#10b981",
    ),
    Provider(
        id="openai",
        name="OpenAI",
        category="official",
        api_format="openai_chat",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4.1",
        secret_slug="openai",
        docs_url="https://platform.openai.com/api-keys",
        icon_color="#10b981",
        # Curated shortlist. When the user wants something outside it, they
        # can either type directly (UI falls back to a free-form input when
        # the typed value isn't in the list) or switch to "Custom" and
        # supply any model string.
        models=("gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini"),
    ),
    Provider(
        id="groq",
        name="Groq",
        category="official",
        api_format="openai_chat",
        base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
        secret_slug="groq",
        docs_url="https://console.groq.com/keys",
        icon_color="#f97316",
        models=(
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
        ),
    ),
    Provider(
        id="ollama-local",
        name="Ollama (local)",
        category="local",
        api_format="openai_chat",
        base_url="http://localhost:11434/v1",
        default_model="llama3.3",
        secret_slug="ollama-local",
        docs_url="https://ollama.ai/",
        icon_color="#64748b",
        notes="No API key required; run `ollama serve` first.",
    ),
)


def by_id(pid: str) -> Provider | None:
    """Lookup a built-in preset by id — case sensitive."""
    for p in BUILTIN_PRESETS:
        if p.id == pid:
            return p
    return None


def default_provider() -> Provider:
    """Preset used when the user hasn't picked anything yet."""
    return BUILTIN_PRESETS[0]


def resolve(
    *,
    provider_id: str = "",
    api_format: str = "",
    base_url: str = "",
    model: str = "",
) -> Provider:
    """Build the Provider instance the dispatcher should call.

    Resolution rules:

    1. If ``provider_id`` names a built-in preset, we return that preset
       with any non-empty ``base_url`` / ``model`` overrides applied.
       This is what's persisted when the user picks a preset from the
       wizard.
    2. If ``provider_id`` is empty or unknown *and* ``api_format`` +
       ``base_url`` are filled, construct an ad-hoc provider on the fly.
       This covers the "Custom" wizard option where config.yaml carries
       ``llm_api_format`` + ``llm_base_url`` instead of a preset id.
    3. Otherwise fall back to :func:`default_provider` so the pipeline
       runs with sane defaults even if config.yaml is stale.
    """
    preset = by_id(provider_id) if provider_id else None
    if preset is not None:
        if (base_url and base_url != preset.base_url) or (model and model != preset.default_model):
            return Provider(
                id=preset.id,
                name=preset.name,
                category=preset.category,
                api_format=preset.api_format,
                base_url=base_url or preset.base_url,
                default_model=model or preset.default_model,
                secret_slug=preset.secret_slug,
                docs_url=preset.docs_url,
                icon=preset.icon,
                icon_color=preset.icon_color,
                notes=preset.notes,
                models=preset.models,
            )
        return preset

    if api_format and base_url and api_format in ("anthropic_http", "openai_chat"):
        return Provider(
            id=provider_id or "custom",
            name="Custom",
            category="custom",
            api_format=api_format,  # type: ignore[arg-type]
            base_url=base_url,
            default_model=model or "",
            secret_slug=provider_id or "custom",
        )

    return default_provider()


def as_dicts() -> list[dict[str, object]]:
    """Serialised form the IPC layer hands to the webview."""
    return [
        {
            "id": p.id,
            "name": p.name,
            "category": p.category,
            "api_format": p.api_format,
            "base_url": p.base_url,
            "default_model": p.default_model,
            "secret_slug": p.secret_slug,
            "docs_url": p.docs_url,
            "icon_color": p.icon_color,
            "notes": p.notes,
            "models": list(p.models),
        }
        for p in BUILTIN_PRESETS
    ]


__all__ = [
    "ApiFormat",
    "Category",
    "Provider",
    "BUILTIN_PRESETS",
    "by_id",
    "default_provider",
    "as_dicts",
    "resolve",
]
