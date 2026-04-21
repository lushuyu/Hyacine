"""Tests for the provider dispatcher and the two new HTTP backends.

We never call the real network in unit tests — :mod:`httpx` exposes a
``MockTransport`` which lets us snoop the outgoing request and hand back
a canned response. The CLI path is covered separately in
``test_claude_code_wrapper.py``.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from hyacine.llm import LlmError, summarize
from hyacine.llm.providers import Provider, by_id, default_provider


@pytest.fixture()
def prompt_file(tmp_path: Path) -> Path:
    p = tmp_path / "system.md"
    p.write_text("You are a test harness.", encoding="utf-8")
    return p


def test_providers_module_contract() -> None:
    """Every built-in preset must have a non-empty name, id, and a known api_format."""
    from hyacine.llm.providers import BUILTIN_PRESETS

    seen_ids: set[str] = set()
    for p in BUILTIN_PRESETS:
        assert p.id, "empty provider id"
        assert p.id not in seen_ids, f"duplicate provider id: {p.id}"
        seen_ids.add(p.id)
        assert p.name
        assert p.api_format in ("anthropic_cli", "anthropic_http", "openai_chat")
        if p.api_format != "anthropic_cli":
            assert p.base_url, f"{p.id!r}: non-CLI provider needs base_url"
    # Sanity: default is the CLI one so existing deployments keep working.
    assert default_provider().api_format == "anthropic_cli"


def test_by_id_roundtrip() -> None:
    p = by_id("openai")
    assert p is not None and p.api_format == "openai_chat"
    assert by_id("does-not-exist") is None


def test_dispatch_unknown_api_format_raises(prompt_file: Path) -> None:
    bogus = Provider(
        id="bogus",
        name="Bogus",
        category="custom",
        api_format="pigeon_net",  # type: ignore[arg-type]
        base_url="https://example.com",
        default_model="x",
        secret_slug="bogus",
    )
    with pytest.raises(LlmError):
        summarize("{}", prompt_file, provider=bogus, api_key="k")


def test_anthropic_http_happy_path(prompt_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Provider with api_format=anthropic_http must POST x-api-key + return content."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["x_api_key"] = request.headers.get("x-api-key")
        captured["auth"] = request.headers.get("authorization")
        body = json.loads(request.content.decode("utf-8"))
        captured["body"] = body
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "assembled summary"}],
            },
        )

    transport = httpx.MockTransport(handler)

    # Replace the module-level httpx.post with one that uses our transport.
    import hyacine.llm.anthropic_http as ah

    original_post = httpx.post

    def fake_post(url: str, **kw: object) -> httpx.Response:
        with httpx.Client(transport=transport) as c:
            return c.post(url, **kw)

    monkeypatch.setattr(ah.httpx, "post", fake_post)
    try:
        out = summarize(
            "{\"hello\": 1}",
            prompt_file,
            provider=Provider(
                id="test",
                name="Test",
                category="custom",
                api_format="anthropic_http",
                base_url="https://relay.example/anthropic",
                default_model="claude-haiku-4-5",
                secret_slug="test",
            ),
            api_key="sk-ant-api03-fake",
            model="claude-sonnet-4-5",
        )
    finally:
        monkeypatch.setattr(ah.httpx, "post", original_post)

    assert out == "assembled summary"
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/v1/messages")
    # x-api-key must be sent — Authorization: Bearer must not.
    assert captured["x_api_key"] == "sk-ant-api03-fake"
    assert captured["auth"] is None
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "claude-sonnet-4-5"
    assert body["system"].startswith("You are a test harness")
    assert body["messages"][0]["role"] == "user"


def test_anthropic_http_non_200_raises(prompt_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import hyacine.llm.anthropic_http as ah

    transport = httpx.MockTransport(lambda _r: httpx.Response(401, text="nope"))

    def fake_post(url: str, **kw: object) -> httpx.Response:
        with httpx.Client(transport=transport) as c:
            return c.post(url, **kw)

    monkeypatch.setattr(ah.httpx, "post", fake_post)
    with pytest.raises(ah.AnthropicHttpError):
        summarize(
            "{}",
            prompt_file,
            provider=Provider(
                id="t",
                name="T",
                category="custom",
                api_format="anthropic_http",
                base_url="https://example.com",
                default_model="m",
                secret_slug="t",
            ),
            api_key="bad",
        )


def test_openai_chat_happy_path(prompt_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """openai_chat must use Authorization: Bearer and /chat/completions."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["x_api_key"] = request.headers.get("x-api-key")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "pong pong"}}
                ]
            },
        )

    import hyacine.llm.openai_chat as oc

    transport = httpx.MockTransport(handler)

    def fake_post(url: str, **kw: object) -> httpx.Response:
        with httpx.Client(transport=transport) as c:
            return c.post(url, **kw)

    monkeypatch.setattr(oc.httpx, "post", fake_post)
    out = summarize(
        "{\"a\": 1}",
        prompt_file,
        provider=by_id("openai"),  # type: ignore[arg-type]
        api_key="sk-openai-xxx",
    )
    assert out == "pong pong"
    assert captured["url"].endswith("/chat/completions")
    assert captured["auth"] == "Bearer sk-openai-xxx"
    assert captured["x_api_key"] is None


def test_openai_chat_allows_empty_key_for_local(prompt_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ollama / LM Studio run unauthenticated — an empty api_key must not
    add an Authorization header."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "local ok"}}]},
        )

    import hyacine.llm.openai_chat as oc

    transport = httpx.MockTransport(handler)

    def fake_post(url: str, **kw: object) -> httpx.Response:
        with httpx.Client(transport=transport) as c:
            return c.post(url, **kw)

    monkeypatch.setattr(oc.httpx, "post", fake_post)
    out = summarize(
        "{}",
        prompt_file,
        provider=by_id("ollama-local"),  # type: ignore[arg-type]
        api_key="",
    )
    assert out == "local ok"
    assert captured["auth"] is None
