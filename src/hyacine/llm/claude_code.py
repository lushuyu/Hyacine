"""Subprocess wrapper for `claude -p` headless invocation.

Critical environment rules (see task brief §1):
  - CLAUDE_CODE_OAUTH_TOKEN must be present.
  - ANTHROPIC_API_KEY and ANTHROPIC_AUTH_TOKEN must be UNSET — otherwise they
    silently override OAuth and bill to the Console account.
  - Parse stdout JSON `result` field. Do NOT trust exit code (known bug).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


class ClaudeCodeError(RuntimeError):
    """Raised when `claude -p` fails to produce a usable result."""


def build_env(base_env: dict[str, str]) -> dict[str, str]:
    """Return a copy of base_env with OAuth kept and API-key vars scrubbed."""
    if "CLAUDE_CODE_OAUTH_TOKEN" not in base_env:
        raise ClaudeCodeError(
            "CLAUDE_CODE_OAUTH_TOKEN is not set in the environment. "
            "Set it before invoking the claude subprocess."
        )
    env = base_env.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    return env


def build_argv(
    system_prompt_path: Path,
    user_message: str,
    *,
    model: str,
    max_turns: int,
    permission_mode: str,
) -> list[str]:
    """Assemble the claude CLI invocation — kept pure for easy testing."""
    if not system_prompt_path.exists():
        raise ClaudeCodeError(
            f"System prompt file not found: {system_prompt_path}"
        )
    return [
        "claude",
        "-p",
        "--output-format", "json",
        "--model", model,
        "--max-turns", str(max_turns),
        "--permission-mode", permission_mode,
        # Empty `--tools ""` disables the built-in toolset. Without this, claude
        # tries to invoke ExitPlanMode / Bash / etc. mid-response and burns
        # turns bouncing off permission denials instead of emitting text.
        "--tools", "",
        "--append-system-prompt-file", str(system_prompt_path),
        "--no-session-persistence",
        user_message,
    ]


def summarize(
    json_input: str,
    system_prompt_path: Path,
    *,
    model: str = "sonnet",
    max_turns: int = 3,
    permission_mode: str = "default",
    timeout_seconds: int = 300,
    user_message: str = "Generate the daily report from the JSON on stdin.",
) -> str:
    """Run `claude -p` with json_input piped to stdin; return the `result` string.

    Raises ClaudeCodeError on any failure path (timeout, non-JSON output,
    missing result field, explicit error in JSON).
    """
    argv = build_argv(
        system_prompt_path,
        user_message,
        model=model,
        max_turns=max_turns,
        permission_mode=permission_mode,
    )
    env = build_env(os.environ.copy())

    try:
        completed = subprocess.run(
            argv,
            input=json_input.encode(),
            capture_output=True,
            env=env,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise ClaudeCodeError(
            f"claude subprocess timed out after {timeout_seconds}s"
        ) from exc

    stdout_text = completed.stdout.decode(errors="replace").strip()
    if not stdout_text:
        stderr_text = completed.stderr.decode(errors="replace").strip()
        raise ClaudeCodeError(
            f"claude subprocess produced no stdout. stderr={stderr_text!r}"
        )

    try:
        data = json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        raise ClaudeCodeError(
            f"claude stdout is not valid JSON: {stdout_text[:200]!r}"
        ) from exc

    # `claude -p --output-format json` emits a list of event objects. The
    # terminal event has type="result" and carries the final text in `result`.
    # Some older / alternate shapes return a single object; accept both.
    result_event: dict | None = None
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("type") == "result":
                result_event = item
        if result_event is None:
            kinds = [
                d.get("type") for d in data if isinstance(d, dict)
            ]
            raise ClaudeCodeError(
                f"claude stdout list had no 'result' event. types={kinds}"
            )
    elif isinstance(data, dict):
        result_event = data
    else:
        raise ClaudeCodeError(
            f"claude stdout JSON has unexpected shape: {type(data).__name__}"
        )

    if result_event.get("is_error") or "error" in result_event:
        detail = result_event.get("error", result_event)
        raise ClaudeCodeError(f"claude returned an error: {detail!r}")

    if "result" not in result_event:
        raise ClaudeCodeError(
            f"claude result event missing 'result' field. keys={list(result_event.keys())}"
        )

    return str(result_event["result"])


__all__ = ["summarize", "build_env", "build_argv", "ClaudeCodeError"]
