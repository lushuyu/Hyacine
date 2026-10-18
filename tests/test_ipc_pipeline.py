"""The desktop sidecar's pipeline.run / pipeline.dry_run handlers.

``hyacine.pipeline.run`` caches Settings and config.yaml in module globals,
which is right for the one-shot CLI/systemd run. The sidecar handlers drop
those caches before each run so a model, language or recipient saved in the
app applies to the next preview or run without restarting the app.

They also tell the app why a run failed and whether the digest may already
be in the inbox (``delivery_uncertain``), so it doesn't invite a re-run that
could mail it twice.
"""
from __future__ import annotations

import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
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


# ---------------------------------------------------------------------------
# Failure reporting: delivery_uncertain + a one-line error
# ---------------------------------------------------------------------------

def _traceback_of(exc: BaseException) -> str:
    try:
        raise exc
    except BaseException:
        return traceback.format_exc()


def _record(status: RunStatus, **kw: Any) -> RunRecord:
    now = datetime.now(UTC)
    return RunRecord(
        id=7, started_at=now, window_from=now, window_to=now, status=status, **kw
    )


def _returning(record: RunRecord) -> Any:
    def fake_run_pipeline(*_a: Any, **_kw: Any) -> RunRecord:
        return record

    return fake_run_pipeline


def test_run_flags_an_uncertain_send(tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """sendMail timed out after the POST went out: the digest may be in the
    inbox, so the app must not just say "Run failed" and invite a re-run."""
    tb = _traceback_of(httpx.ReadTimeout("timed out")) + f"{run_module._DELIVERY_UNKNOWN_NOTE}\n"
    record = _record(RunStatus.FAILED, error_traceback=tb, delivery_uncertain=True)
    monkeypatch.setattr(run_module, "run_pipeline", _returning(record))

    res = pipeline_h.run(emit=_noop, log=_noop)

    assert res["ok"] is False
    assert res["delivery_uncertain"] is True
    # The final exception, without the note meant for the dashboard.
    assert res["error"] == "httpx.ReadTimeout: timed out"
    assert res["record"]["status"] == "failed"


def test_run_gives_the_reason_for_a_recorded_failure(
    tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tb = _traceback_of(RuntimeError("AADSTS700082: refresh token expired.\nTrace ID: abc"))
    record = _record(RunStatus.FAILED, error_traceback=tb)
    monkeypatch.setattr(run_module, "run_pipeline", _returning(record))

    res = pipeline_h.run(emit=_noop, log=_noop)

    assert res["ok"] is False
    assert res["delivery_uncertain"] is False
    assert res["error"] == "RuntimeError: AADSTS700082: refresh token expired. Trace ID: abc"


def test_run_failure_without_traceback_still_has_an_error(
    tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_module, "run_pipeline", _returning(_record(RunStatus.FAILED)))

    res = pipeline_h.run(emit=_noop, log=_noop)

    assert res["ok"] is False
    assert res["delivery_uncertain"] is False
    assert res["error"] == "no error details were recorded"


def test_successful_run_has_no_error(tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record = _record(RunStatus.SUCCESS, email_count=3, sent_message_id="m-1")
    monkeypatch.setattr(run_module, "run_pipeline", _returning(record))

    res = pipeline_h.run(emit=_noop, log=_noop)

    assert res["ok"] is True
    assert res["delivery_uncertain"] is False
    assert "error" not in res
    assert res["record"] == {
        "id": 7,
        "status": "success",
        "email_count": 3,
        "sent_message_id": "m-1",
    }


@pytest.mark.parametrize(
    ("exc", "uncertain", "error"),
    [
        (
            run_module.DeliveredButNotRecorded("m-1"),
            True,
            "hyacine.pipeline.run.DeliveredButNotRecorded: digest sent (sent_message_id=m-1)"
            " but the run was not recorded; watermark not advanced",
        ),
        (
            run_module.DeliveredButNotRecorded(None, outcome_unknown=True),
            True,
            "hyacine.pipeline.run.DeliveredButNotRecorded: sendMail outcome unknown"
            " but the run was not recorded; watermark not advanced",
        ),
        (
            ValueError("recipient_email is not configured.\nRun init."),
            False,
            "ValueError: recipient_email is not configured. Run init.",
        ),
    ],
)
def test_run_that_raises(
    tmp_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    exc: Exception,
    uncertain: bool,
    error: str,
) -> None:
    def fake_run_pipeline(*_a: Any, **_kw: Any) -> RunRecord:
        raise exc from OSError("database is locked")

    monkeypatch.setattr(run_module, "run_pipeline", fake_run_pipeline)
    stages: list[tuple[str, str]] = []

    def emit(_event: str, payload: Any) -> None:
        stages.append((payload["stage"], payload["status"]))

    res = pipeline_h.run(emit=emit, log=_noop)

    assert res["ok"] is False
    assert res["delivery_uncertain"] is uncertain
    # The final exception, on one line (not the OSError it was raised from).
    assert res["error"] == error
    assert stages == [(stage, "fail") for stage in pipeline_h._STAGES]


def test_dry_run_gives_the_reason_for_a_recorded_failure(
    tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tb = _traceback_of(RuntimeError("Not logged in.\nRun claude login."))
    record = _record(RunStatus.FAILED, error_traceback=tb)
    monkeypatch.setattr(run_module, "run_pipeline", _returning(record))

    res = pipeline_h.dry_run(emit=_noop, log=_noop)

    assert res["ok"] is False
    assert res["error"] == "RuntimeError: Not logged in. Run claude login."


def test_dry_run_that_raises_gives_a_one_line_error(
    tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run_pipeline(*_a: Any, **_kw: Any) -> RunRecord:
        raise ValueError("recipient_email is not configured.\nRun init.")

    monkeypatch.setattr(run_module, "run_pipeline", fake_run_pipeline)

    res = pipeline_h.dry_run(emit=_noop, log=_noop)

    assert res["ok"] is False
    assert res["error"] == "ValueError: recipient_email is not configured. Run init."


def test_successful_dry_run_has_no_error(tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record = _record(RunStatus.SUCCESS, markdown="# Today\n", sent_message_id="(dry-run)")
    monkeypatch.setattr(run_module, "run_pipeline", _returning(record))
    # The preview render is covered elsewhere; keep this test about the result.
    monkeypatch.setattr(pipeline_h, "_markdown_to_html", lambda md: f"<pre>{md}</pre>")

    res = pipeline_h.dry_run(emit=_noop, log=_noop)

    assert res["ok"] is True
    assert "error" not in res
