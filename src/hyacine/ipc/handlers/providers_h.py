"""IPC handlers for provider selection + per-provider connectivity tests.

Exposes three methods to the desktop shell:

* ``providers.list``   — built-in preset catalogue serialised to JSON.
* ``providers.current``— the active preset (from config.yaml).
* ``providers.test``   — run a minimal "ping" request against one
                         provider + key combination. The implementation
                         dispatches on ``api_format``; the CLI variant
                         requires the ``claude`` binary to be reachable
                         on PATH.

Secrets flow the same way as everywhere else: the Rust parent fetches the
key from the OS keychain and passes it into ``providers.test`` as a
parameter. The sidecar does not read the keychain itself. Its only other
key is ``HYACINE_LLM_API_KEY``, which belongs to the provider that was
active when the sidecar spawned, so ``providers.test`` only falls back to
it when the tested endpoint is the active one (see :func:`_env_key_for`).
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from collections.abc import Callable
from typing import Any

import httpx

from hyacine.llm import providers as _providers
from hyacine.llm.providers import DEFAULT_CLAUDE_MODEL, Provider


def list_providers() -> dict[str, Any]:
    return {"providers": _providers.as_dicts()}


def current_provider() -> dict[str, Any]:
    """Return the provider the pipeline would actually use right now.

    Always returns a concrete provider — ``resolve()`` falls back to the
    default preset when the config is empty or points at an unknown id —
    so the frontend never has to guess what the runtime will see. The
    ``resolved_from`` flag tells the UI which branch fired so it can hint
    when a preset was missing ("stale config; using Claude Code OAuth").
    """
    from hyacine.config import get_settings, load_yaml_config

    s = get_settings()
    cfg = load_yaml_config(s.config_path)
    pid = cfg.llm_provider
    p = _providers.resolve(
        provider_id=pid,
        api_format=cfg.llm_api_format,
        base_url=cfg.llm_base_url,
        model=cfg.llm_model,
    )

    # Best-effort signal for the UI about why we ended up here.
    if pid and _providers.by_id(pid) is not None:
        resolved_from = "preset"
    elif pid == "" and cfg.llm_api_format and cfg.llm_base_url:
        resolved_from = "custom"
    elif pid:
        resolved_from = "fallback_default"
    else:
        resolved_from = "default"

    return {
        "current": {
            "id": p.id,
            "name": p.name,
            "api_format": p.api_format,
            "base_url": p.base_url,
            "default_model": p.default_model,
            "secret_slug": p.secret_slug,
        },
        "resolved_from": resolved_from,
    }


def _now_ms() -> int:
    return int(time.monotonic() * 1000)


def test(  # noqa: C901 — mirrors providers.api_format branches; keeping a single function is clearer
    *,
    provider_id: str = "",
    base_url: str = "",
    api_format: str = "",
    api_key: str = "",
    model: str = "",
    emit: Callable[[str, Any], None] | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Run a minimal end-to-end probe for the chosen provider.

    Callers can either reference a built-in preset by ``provider_id`` *or*
    supply the raw fields (``base_url`` + ``api_format``) for a custom
    endpoint. Returns the familiar connectivity-probe shape
    ``{kind, status, latency_ms, detail}`` so the wizard UI can reuse
    existing card components.
    """
    preset: Provider | None = _providers.by_id(provider_id) if provider_id else None
    effective_format = api_format or (preset.api_format if preset else "")
    effective_base = base_url or (preset.base_url if preset else "")
    effective_model = model or (preset.default_model if preset else "")

    if not effective_format:
        return _fail("providers.test", "missing api_format")

    # Secrets never round-trip to the webview — when the key was stored via
    # the wizard, the UI only has `has()`, not the plaintext. The Rust
    # parent populates `HYACINE_LLM_API_KEY` at sidecar spawn for the
    # active provider's slug, so fall back to it, but only for that
    # provider's endpoint: any other provider would receive a foreign key.
    effective_key = api_key or _env_key_for(effective_format, effective_base)

    # Local providers (Ollama, LM Studio, etc.) run unauthenticated; treat
    # an empty key as "no auth header needed" rather than a validation
    # failure. Matches what :mod:`hyacine.llm.openai_chat` does in the
    # real pipeline.
    is_local = bool(preset and preset.category == "local") or (
        effective_base.startswith("http://localhost")
        or effective_base.startswith("http://127.0.0.1")
    )

    if effective_format == "anthropic_cli":
        return _probe_anthropic_cli(api_key=effective_key, model=effective_model)
    if effective_format == "anthropic_http":
        if not effective_base:
            return _fail("providers.test", "missing base_url for anthropic_http")
        if not effective_key:
            return _fail("providers.test", f"anthropic_http requires an api_key{_NO_KEY_HINT}")
        return _probe_anthropic_http(effective_base, effective_key, effective_model)
    if effective_format == "openai_chat":
        if not effective_base:
            return _fail("providers.test", "missing base_url for openai_chat")
        if not effective_key and not is_local:
            return _fail(
                "providers.test",
                f"openai_chat requires an api_key (non-local provider){_NO_KEY_HINT}",
            )
        return _probe_openai_chat(effective_base, effective_key, effective_model)
    return _fail("providers.test", f"unknown api_format: {effective_format!r}")


_NO_KEY_HINT = (
    "; enter the key to test it (a stored key is only used for the active provider)"
)


def _env_key_for(api_format: str, base_url: str) -> str:
    """Return ``HYACINE_LLM_API_KEY`` if the probe targets the active endpoint.

    The Rust parent exports the active provider's keychain secret in that
    variable when it spawns the sidecar. Using it to test another provider
    would hand, say, an Anthropic Console key to DeepSeek or a localhost
    server. So it is only returned when the tested ``api_format`` and
    ``base_url`` match the provider ``config.yaml`` makes active — the same
    endpoint the daily run sends this key to. ``anthropic_cli`` never takes
    it: the CLI authenticates with ``CLAUDE_CODE_OAUTH_TOKEN`` (already in
    the sidecar env when the CLI is active) or its own ``claude login``.
    """
    env_key = os.environ.get("HYACINE_LLM_API_KEY", "")
    if not env_key or api_format == "anthropic_cli":
        return ""
    from hyacine.config import get_settings, load_yaml_config  # noqa: PLC0415

    try:
        cfg = load_yaml_config(get_settings().config_path)
    except Exception:  # noqa: BLE001 — unreadable config: no provider is known to be active
        return ""
    active = _providers.resolve(
        provider_id=cfg.llm_provider,
        api_format=cfg.llm_api_format,
        base_url=cfg.llm_base_url,
        model=cfg.llm_model,
    )
    if active.api_format != api_format:
        return ""
    if active.base_url.rstrip("/") != base_url.rstrip("/"):
        return ""
    return env_key


# ── Individual probes ──────────────────────────────────────────────────────


def _probe_anthropic_cli(*, api_key: str, model: str) -> dict[str, Any]:
    """Invoke ``claude -p "ping"`` using an optional OAuth token or existing CLI credentials.

    The ``api_key`` parameter is optional. When non-empty we export it as
    ``CLAUDE_CODE_OAUTH_TOKEN`` for the subprocess; when empty, ``claude``
    falls back to its own credential store (populated by ``claude login``
    at ``~/.claude/`` or the platform keychain). Either path is a
    legitimate "configured" state, so we let the CLI resolve auth and
    surface whatever error comes back if neither source has creds —
    rather than pre-failing with a confusing "skipped" verdict.

    Genuine blockers (the ``claude`` binary itself being absent) still fail
    loud; that's what the :func:`resolve_claude_bin` branch below catches.

    The env comes from :func:`build_env` and the child runs from an empty
    temp dir, as in the daily run, so the probe gets the same API-key
    scrubbing, safe mode and effort validation and can't pass on a setup
    the real run would reject.
    """
    from hyacine.llm.claude_code import (  # noqa: PLC0415
        ClaudeCodeError,
        build_env,
        resolve_claude_bin,
    )

    start = _now_ms()
    base_env = os.environ.copy()
    if api_key.strip():
        base_env["CLAUDE_CODE_OAUTH_TOKEN"] = api_key.strip()
    try:
        env = build_env(base_env)
    except ClaudeCodeError as e:
        return _fail("providers.test", str(e))
    try:
        bin_path = resolve_claude_bin(env)
    except Exception as e:  # noqa: BLE001
        return {
            "kind": "providers.test",
            "status": "fail",
            "latency_ms": 0,
            "detail": f"`claude` CLI not found: {e}",
        }

    argv = [
        bin_path,
        "-p",
        "--output-format", "text",
        "--model", model or DEFAULT_CLAUDE_MODEL,
        "--max-turns", "1",
        "--tools", "",
        "--permission-mode", "default",
        "--no-session-persistence",
        "Reply with the single word 'pong'.",
    ]
    try:
        with tempfile.TemporaryDirectory(
            prefix="hyacine-claude-", ignore_cleanup_errors=True
        ) as workdir:
            completed = subprocess.run(
                argv,
                # The sidecar's stdin is the JSON-RPC channel. Inheriting it
                # makes `claude -p` wait on stdin (~3 s) and lets it swallow
                # RPC frames meant for us.
                stdin=subprocess.DEVNULL,
                capture_output=True,
                env=env,
                cwd=workdir,
                timeout=30,
            )
    except subprocess.TimeoutExpired:
        return {
            "kind": "providers.test",
            "status": "fail",
            "latency_ms": _now_ms() - start,
            "detail": "timed out after 30s",
        }
    except OSError as e:
        return {
            "kind": "providers.test",
            "status": "fail",
            "latency_ms": _now_ms() - start,
            "detail": f"could not execute `claude` at {bin_path!r}: {e}",
        }
    latency = _now_ms() - start
    if completed.returncode != 0:
        stderr = completed.stderr.decode(errors="replace").strip()[:400]
        return {
            "kind": "providers.test",
            "status": "fail",
            "latency_ms": latency,
            "detail": f"exit {completed.returncode}: {stderr}",
        }
    stdout = completed.stdout.decode(errors="replace").strip()[:200]
    return {
        "kind": "providers.test",
        "status": "ok",
        "latency_ms": latency,
        "detail": f"`claude` replied: {stdout!r}",
    }


def _probe_anthropic_http(base_url: str, api_key: str, model: str) -> dict[str, Any]:
    """Small /v1/messages round-trip."""
    start = _now_ms()
    url = base_url.rstrip("/") + "/v1/messages"
    body = {
        "model": model or DEFAULT_CLAUDE_MODEL,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "ping"}],
    }
    try:
        r = httpx.post(
            url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
            timeout=15.0,
        )
    except httpx.HTTPError as e:
        return {
            "kind": "providers.test",
            "status": "fail",
            "latency_ms": _now_ms() - start,
            "detail": str(e),
        }
    latency = _now_ms() - start
    if r.status_code == 200:
        return {
            "kind": "providers.test",
            "status": "ok",
            "latency_ms": latency,
            "detail": f"HTTP 200, model={model}",
        }
    return {
        "kind": "providers.test",
        "status": "fail",
        "latency_ms": latency,
        "detail": f"HTTP {r.status_code}: {r.text[:300]}",
    }


def _probe_openai_chat(base_url: str, api_key: str, model: str) -> dict[str, Any]:
    """Small /chat/completions round-trip."""
    start = _now_ms()
    url = base_url.rstrip("/") + "/chat/completions"
    headers: dict[str, str] = {"content-type": "application/json"}
    if api_key.strip():
        headers["authorization"] = f"Bearer {api_key.strip()}"
    body = {
        "model": model or "gpt-4o-mini",
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "ping"}],
    }
    try:
        r = httpx.post(url, headers=headers, json=body, timeout=15.0)
    except httpx.HTTPError as e:
        return {
            "kind": "providers.test",
            "status": "fail",
            "latency_ms": _now_ms() - start,
            "detail": str(e),
        }
    latency = _now_ms() - start
    if r.status_code == 200:
        return {
            "kind": "providers.test",
            "status": "ok",
            "latency_ms": latency,
            "detail": f"HTTP 200, model={model}",
        }
    return {
        "kind": "providers.test",
        "status": "fail",
        "latency_ms": latency,
        "detail": f"HTTP {r.status_code}: {r.text[:300]}",
    }


def _fail(kind: str, detail: str) -> dict[str, Any]:
    return {"kind": kind, "status": "fail", "latency_ms": 0, "detail": detail}


__all__ = ["current_provider", "list_providers", "test"]
