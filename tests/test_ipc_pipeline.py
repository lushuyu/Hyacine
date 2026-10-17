"""The long-lived desktop sidecar picks up config edits between runs.

``hyacine.pipeline.run`` caches Settings and config.yaml in module globals,
which is right for the one-shot CLI/systemd run. The sidecar handlers drop
those caches before each run so a model, language or recipient saved in the
app applies to the next preview or run without restarting the app.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import hyacine.pipeline.run as run_module
from hyacine.ipc.handlers import config_h, pipeline_h
from hyacine.models import RunRecord, RunStatus


@pytest.fixture
def tmp_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "config").mkdir()
    for leak in (
        "HYACINE_RULES_PATH",
        "HYACINE_PROMPT_PATH",
        "HYACINE_DB_PATH",
        "HYACINE_AUTH_DIR",
        "HYACINE_LOG_DIR",
        "HYACINE_AUTH_RECORD_PATH",
        "HYACINE_NTFY_TOPIC",
        # dry_run() copies this into CLAUDE_CODE_OAUTH_TOKEN for good.
        "HYACINE_CLAUDE_CODE_OAUTH_TOKEN",
        # YamlConfig reads these from the environment too.
        "LLM_MODEL",
        "LANGUAGE",
    ):
        monkeypatch.delenv(leak, raising=False)
    monkeypatch.setenv("HYACINE_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("HYACINE_CONFIG_PATH", str(tmp_path / "config" / "config.yaml"))
    # Whatever the handlers leave cached is undone after the test.
    monkeypatch.setattr(run_module, "_settings", None)
    monkeypatch.setattr(run_module, "_cfg", None)
    return tmp_path


def _noop(*_a: Any, **_kw: Any) -> None:
    return None


def test_each_run_reads_the_current_config(
    tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, str, str]] = []

    def fake_run_pipeline(*_a: Any, **_kw: Any) -> RunRecord:
        cfg = run_module._get_cfg()
        seen.append((cfg.llm_model, cfg.language, run_module._get_settings().ntfy_topic))
        now = datetime.now(UTC)
        return RunRecord(
            started_at=now, window_from=now, window_to=now, status=RunStatus.SUCCESS
        )

    monkeypatch.setattr(run_module, "run_pipeline", fake_run_pipeline)

    config_h.write_config(llm_model="claude-opus-4-7", language="en")
    pipeline_h.dry_run(emit=_noop, log=_noop)

    config_h.write_config(llm_model="claude-opus-5-5", language="zh-CN")
    monkeypatch.setenv("HYACINE_NTFY_TOPIC", "new-topic")
    pipeline_h.dry_run(emit=_noop, log=_noop)
    pipeline_h.run(emit=_noop, log=_noop)

    assert seen == [
        ("claude-opus-4-7", "en", ""),
        ("claude-opus-5-5", "zh-CN", "new-topic"),
        ("claude-opus-5-5", "zh-CN", "new-topic"),
    ]
