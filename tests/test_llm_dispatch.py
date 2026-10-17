"""Tests for the provider dispatcher and the two new HTTP backends.

We never call the real network in unit tests — :mod:`httpx` exposes a
``MockTransport`` which lets us snoop the outgoing request and hand back
a canned response. The CLI path is covered separately in
``test_claude_code_wrapper.py``.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType

import httpx
import pytest

from hyacine.llm import LlmError, anthropic_http, openai_chat, summarize
from hyacine.llm.providers import Provider, by_id, default_provider


@pytest.fixture()
def prompt_file(tmp_path: Path) -> Path:
    p = tmp_path / "system.md"
    p.write_text("You are a test harness.", encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def _no_max_tokens_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep an operator's own override out of the max_tokens assertions.
    monkeypatch.delenv("HYACINE_LLM_MAX_TOKENS", raising=False)


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


# ---------------------------------------------------------------------------
# anthropic_http: first-party vs relay request body, stop_reason handling
# ---------------------------------------------------------------------------

FIRST_PARTY = "https://api.anthropic.com"
RELAY = "https://api.deepseek.com/anthropic"


def _mock_post(
    monkeypatch: pytest.MonkeyPatch, module: ModuleType, payload: dict[str, object]
) -> dict[str, object]:
    """Route ``module.httpx.post`` to a MockTransport returning ``payload``.

    Returns a dict that fills with the outgoing request's headers and body.
    """
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)

    def fake_post(url: str, **kw: object) -> httpx.Response:
        with httpx.Client(transport=transport) as c:
            return c.post(url, **kw)

    monkeypatch.setattr(module.httpx, "post", fake_post)
    return captured


def _ok(text: str = "digest") -> dict[str, object]:
    return {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn"}


def _call_anthropic(prompt_file: Path, *, base_url: str, model: str) -> str:
    return anthropic_http.summarize(
        "{}", prompt_file, base_url=base_url, api_key="k", model=model
    )


@pytest.fixture()
def _no_effort_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYACINE_CLAUDE_EFFORT", raising=False)


@pytest.mark.usefixtures("_no_effort_env")
@pytest.mark.parametrize(
    "model", ["claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"]
)
def test_anthropic_http_first_party_current_model_body(
    prompt_file: Path, monkeypatch: pytest.MonkeyPatch, model: str
) -> None:
    captured = _mock_post(monkeypatch, anthropic_http, _ok())
    assert _call_anthropic(prompt_file, base_url=FIRST_PARTY, model=model) == "digest"

    body = captured["body"]
    assert isinstance(body, dict)
    assert body["max_tokens"] == 16000
    assert body["output_config"] == {"effort": "high"}
    assert body["fallbacks"] == "default"
    # Sampling knobs are rejected on these models; thinking is always on.
    for key in ("temperature", "top_p", "top_k", "thinking"):
        assert key not in body
    headers = captured["headers"]
    assert isinstance(headers, httpx.Headers)
    assert headers["anthropic-beta"] == "server-side-fallback-2026-07-01"
    assert headers["x-api-key"] == "k"
    assert headers["anthropic-version"] == "2023-06-01"


@pytest.mark.usefixtures("_no_effort_env")
@pytest.mark.parametrize(
    "model",
    [
        "claude-haiku-5-5",
        "claude-opus-4-7",
        "claude-opus-4-8",
        "claude-fable-5",
        "claude-sonnet-5",
    ],
)
def test_anthropic_http_first_party_effort_without_fallback(
    prompt_file: Path, monkeypatch: pytest.MonkeyPatch, model: str
) -> None:
    """These accept effort but not the server-side refusal fallback."""
    captured = _mock_post(monkeypatch, anthropic_http, _ok())
    _call_anthropic(prompt_file, base_url=FIRST_PARTY, model=model)

    body = captured["body"]
    assert isinstance(body, dict)
    assert body["max_tokens"] == 16000
    assert body["output_config"] == {"effort": "high"}
    assert "fallbacks" not in body
    headers = captured["headers"]
    assert isinstance(headers, httpx.Headers)
    assert "anthropic-beta" not in headers


@pytest.mark.usefixtures("_no_effort_env")
@pytest.mark.parametrize(
    "model",
    ["claude-haiku-4-5", "claude-sonnet-4-5", "claude-opus-4-6", "claude-sonnet-4-6"],
)
def test_anthropic_http_first_party_older_model_skips_effort(
    prompt_file: Path, monkeypatch: pytest.MonkeyPatch, model: str
) -> None:
    captured = _mock_post(monkeypatch, anthropic_http, _ok())
    _call_anthropic(prompt_file, base_url=FIRST_PARTY + "/", model=model)

    body = captured["body"]
    assert isinstance(body, dict)
    assert body["max_tokens"] == 16000
    assert "output_config" not in body
    assert "fallbacks" not in body
    headers = captured["headers"]
    assert isinstance(headers, httpx.Headers)
    assert "anthropic-beta" not in headers


@pytest.mark.parametrize(
    "base_url",
    [RELAY, "https://api.moonshot.cn/anthropic", "https://api.anthropic.com.evil.example"],
)
def test_anthropic_http_relay_gets_core_contract_only(
    prompt_file: Path, monkeypatch: pytest.MonkeyPatch, base_url: str
) -> None:
    """Relays forward claude-* ids too, but reject the first-party extras."""
    monkeypatch.setenv("HYACINE_CLAUDE_EFFORT", "max")
    captured = _mock_post(monkeypatch, anthropic_http, _ok())
    _call_anthropic(prompt_file, base_url=base_url, model="claude-opus-5-5")

    body = captured["body"]
    assert isinstance(body, dict)
    assert body["max_tokens"] == 4096
    assert "output_config" not in body
    assert "fallbacks" not in body
    headers = captured["headers"]
    assert isinstance(headers, httpx.Headers)
    assert "anthropic-beta" not in headers


def test_anthropic_http_effort_env_override(
    prompt_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HYACINE_CLAUDE_EFFORT", " XHigh ")
    captured = _mock_post(monkeypatch, anthropic_http, _ok())
    _call_anthropic(prompt_file, base_url=FIRST_PARTY, model="claude-opus-5-5")
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["output_config"] == {"effort": "xhigh"}
    assert body["max_tokens"] == 64000


@pytest.mark.parametrize("effort", ["xhigh", "max"])
@pytest.mark.parametrize("model", ["claude-opus-5-5", "claude-haiku-5-5"])
def test_anthropic_http_high_effort_raises_default_budget(
    prompt_file: Path, monkeypatch: pytest.MonkeyPatch, effort: str, model: str
) -> None:
    """Anthropic needs max_tokens >= 64000 at xhigh / max."""
    monkeypatch.setenv("HYACINE_CLAUDE_EFFORT", effort)
    captured = _mock_post(monkeypatch, anthropic_http, _ok())
    _call_anthropic(prompt_file, base_url=FIRST_PARTY, model=model)
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["output_config"] == {"effort": effort}
    assert body["max_tokens"] == 64000


@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_anthropic_http_lower_effort_keeps_default_budget(
    prompt_file: Path, monkeypatch: pytest.MonkeyPatch, effort: str
) -> None:
    monkeypatch.setenv("HYACINE_CLAUDE_EFFORT", effort)
    captured = _mock_post(monkeypatch, anthropic_http, _ok())
    _call_anthropic(prompt_file, base_url=FIRST_PARTY, model="claude-opus-5-5")
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["max_tokens"] == 16000


def test_anthropic_http_high_effort_ignored_for_model_without_effort(
    prompt_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No effort is sent to claude-haiku-4-5, so its budget stays at 16000."""
    monkeypatch.setenv("HYACINE_CLAUDE_EFFORT", "max")
    captured = _mock_post(monkeypatch, anthropic_http, _ok())
    _call_anthropic(prompt_file, base_url=FIRST_PARTY, model="claude-haiku-4-5")
    body = captured["body"]
    assert isinstance(body, dict)
    assert "output_config" not in body
    assert body["max_tokens"] == 16000


@pytest.mark.parametrize(
    ("base_url", "model"),
    [
        (FIRST_PARTY, "claude-opus-5-5"),
        (FIRST_PARTY, "claude-haiku-4-5"),
        (RELAY, "claude-opus-5-5"),
    ],
)
def test_anthropic_http_max_tokens_env_override(
    prompt_file: Path, monkeypatch: pytest.MonkeyPatch, base_url: str, model: str
) -> None:
    """The override beats every default, including the xhigh / max one."""
    monkeypatch.setenv("HYACINE_CLAUDE_EFFORT", "max")
    monkeypatch.setenv("HYACINE_LLM_MAX_TOKENS", " 32000 ")
    captured = _mock_post(monkeypatch, anthropic_http, _ok())
    _call_anthropic(prompt_file, base_url=base_url, model=model)
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["max_tokens"] == 32000


@pytest.mark.parametrize("value", ["0", "-1", "abc", "1.5", "16k"])
def test_anthropic_http_max_tokens_env_invalid(
    prompt_file: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("HYACINE_LLM_MAX_TOKENS", value)
    captured = _mock_post(monkeypatch, anthropic_http, _ok())
    with pytest.raises(
        anthropic_http.AnthropicHttpError,
        match="HYACINE_LLM_MAX_TOKENS=.* is not a positive integer",
    ):
        _call_anthropic(prompt_file, base_url=RELAY, model="m")
    assert captured == {}, "no request should be sent with a bad max_tokens value"


def test_anthropic_http_effort_env_invalid(
    prompt_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HYACINE_CLAUDE_EFFORT", "ultra")
    captured = _mock_post(monkeypatch, anthropic_http, _ok())
    with pytest.raises(anthropic_http.AnthropicHttpError, match="HYACINE_CLAUDE_EFFORT"):
        _call_anthropic(prompt_file, base_url=FIRST_PARTY, model="claude-opus-5-5")
    assert captured == {}, "no request should be sent with a bad effort value"


@pytest.mark.usefixtures("_no_effort_env")
def test_anthropic_http_skips_thinking_and_fallback_blocks(
    prompt_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_post(
        monkeypatch,
        anthropic_http,
        {
            "content": [
                {"type": "thinking", "thinking": "", "signature": "sig"},
                {
                    "type": "fallback",
                    "from": {"model": "claude-opus-5-5"},
                    "to": {"model": "claude-opus-5"},
                },
                {"type": "text", "text": "  part one, "},
                {"type": "text", "text": "part two  "},
            ],
            "stop_reason": "end_turn",
            "stop_details": None,
        },
    )
    out = _call_anthropic(prompt_file, base_url=FIRST_PARTY, model="claude-opus-5-5")
    assert out == "part one, part two"


@pytest.mark.usefixtures("_no_effort_env")
def test_anthropic_http_refusal_raises_with_details(
    prompt_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_post(
        monkeypatch,
        anthropic_http,
        {
            "content": [],
            "stop_reason": "refusal",
            "stop_details": {
                "type": "refusal",
                "category": "cyber",
                "explanation": "declined by safety classifier",
            },
        },
    )
    with pytest.raises(anthropic_http.AnthropicHttpError) as exc:
        _call_anthropic(prompt_file, base_url=FIRST_PARTY, model="claude-opus-5-5")
    assert "refused" in str(exc.value)
    assert "cyber" in str(exc.value)
    assert "declined by safety classifier" in str(exc.value)


def test_anthropic_http_refusal_without_details_still_raises(
    prompt_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stop_details may be null; partial text on a refusal is never returned."""
    _mock_post(
        monkeypatch,
        anthropic_http,
        {
            "content": [{"type": "text", "text": "partial"}],
            "stop_reason": "refusal",
            "stop_details": None,
        },
    )
    with pytest.raises(anthropic_http.AnthropicHttpError, match="refused"):
        _call_anthropic(prompt_file, base_url=RELAY, model="m")


@pytest.mark.parametrize("stop", ["max_tokens", "model_context_window_exceeded"])
def test_anthropic_http_truncation_raises(
    prompt_file: Path, monkeypatch: pytest.MonkeyPatch, stop: str
) -> None:
    _mock_post(
        monkeypatch,
        anthropic_http,
        {"content": [{"type": "text", "text": "half a digest"}], "stop_reason": stop},
    )
    with pytest.raises(anthropic_http.AnthropicHttpError, match="truncated"):
        _call_anthropic(prompt_file, base_url=RELAY, model="m")


def test_anthropic_http_max_tokens_truncation_hints_at_fix(
    prompt_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_post(
        monkeypatch,
        anthropic_http,
        {"content": [{"type": "text", "text": "half"}], "stop_reason": "max_tokens"},
    )
    with pytest.raises(anthropic_http.AnthropicHttpError) as exc:
        _call_anthropic(prompt_file, base_url=RELAY, model="m")
    assert str(exc.value) == (
        "output truncated (stop_reason=max_tokens); the digest would be incomplete"
        "; raise HYACINE_LLM_MAX_TOKENS (and llm_timeout_seconds) "
        "or lower HYACINE_CLAUDE_EFFORT"
    )


def test_anthropic_http_context_window_truncation_has_no_budget_hint(
    prompt_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A full context window is an input problem; more output budget won't help."""
    _mock_post(
        monkeypatch,
        anthropic_http,
        {"content": [], "stop_reason": "model_context_window_exceeded"},
    )
    with pytest.raises(anthropic_http.AnthropicHttpError) as exc:
        _call_anthropic(prompt_file, base_url=RELAY, model="m")
    assert "HYACINE_LLM_MAX_TOKENS" not in str(exc.value)


def test_anthropic_http_string_content_returned(
    prompt_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_post(monkeypatch, anthropic_http, {"content": "  relay text  "})
    assert _call_anthropic(prompt_file, base_url=RELAY, model="m") == "relay text"


@pytest.mark.parametrize(
    "content",
    [
        "",
        "   \n",
        [],
        [{"type": "thinking", "thinking": "", "signature": "sig"}],
        [{"type": "text", "text": "  "}],
    ],
)
def test_anthropic_http_empty_content_raises(
    prompt_file: Path, monkeypatch: pytest.MonkeyPatch, content: object
) -> None:
    _mock_post(monkeypatch, anthropic_http, {"content": content, "stop_reason": "end_turn"})
    with pytest.raises(anthropic_http.AnthropicHttpError, match="text content"):
        _call_anthropic(prompt_file, base_url=RELAY, model="m")


# ---------------------------------------------------------------------------
# openai_chat: finish_reason handling
# ---------------------------------------------------------------------------


def _call_openai(prompt_file: Path) -> str:
    return openai_chat.summarize(
        "{}", prompt_file, base_url="https://api.openai.com/v1", api_key="k", model="m"
    )


def test_openai_chat_finish_reason_stop_ok(
    prompt_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_post(
        monkeypatch,
        openai_chat,
        {"choices": [{"message": {"content": "all good"}, "finish_reason": "stop"}]},
    )
    assert _call_openai(prompt_file) == "all good"


@pytest.mark.parametrize(
    ("finish", "match"),
    [("length", "truncated"), ("content_filter", "content filter")],
)
def test_openai_chat_bad_finish_reason_raises(
    prompt_file: Path, monkeypatch: pytest.MonkeyPatch, finish: str, match: str
) -> None:
    _mock_post(
        monkeypatch,
        openai_chat,
        {"choices": [{"message": {"content": "half a dig"}, "finish_reason": finish}]},
    )
    with pytest.raises(openai_chat.OpenAiChatError, match=match):
        _call_openai(prompt_file)


def test_openai_chat_length_truncation_hints_at_fix(
    prompt_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_post(
        monkeypatch,
        openai_chat,
        {"choices": [{"message": {"content": "half"}, "finish_reason": "length"}]},
    )
    with pytest.raises(openai_chat.OpenAiChatError) as exc:
        _call_openai(prompt_file)
    assert str(exc.value) == (
        "output truncated (finish_reason=length); the digest would be incomplete"
        "; raise HYACINE_LLM_MAX_TOKENS"
    )


@pytest.mark.parametrize(("value", "expected"), [(None, 4096), (" 8192 ", 8192)])
def test_openai_chat_max_tokens(
    prompt_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
    expected: int,
) -> None:
    if value is not None:
        monkeypatch.setenv("HYACINE_LLM_MAX_TOKENS", value)
    captured = _mock_post(
        monkeypatch,
        openai_chat,
        {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]},
    )
    _call_openai(prompt_file)
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["max_tokens"] == expected


@pytest.mark.parametrize("value", ["0", "-1", "abc", "1.5"])
def test_openai_chat_max_tokens_env_invalid(
    prompt_file: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("HYACINE_LLM_MAX_TOKENS", value)
    captured = _mock_post(
        monkeypatch,
        openai_chat,
        {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]},
    )
    with pytest.raises(
        openai_chat.OpenAiChatError,
        match="HYACINE_LLM_MAX_TOKENS=.* is not a positive integer",
    ):
        _call_openai(prompt_file)
    assert captured == {}, "no request should be sent with a bad max_tokens value"
