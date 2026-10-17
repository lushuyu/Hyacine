"""End-to-end pipeline: watermark → fetch → LLM → send → persist → ping hc.

Contract:
  - Read last_successful_run_at from DB. If absent, backfill to now-24h.
  - Fetch window = [last_successful_run_at, now UTC].
  - Fetch today's calendar in local tz.
  - Run rules classifier on emails.
  - Assemble FetchResult, serialize, hand to LLM.
  - sendMail on success → update watermark.
  - Failures: record traceback in the run row; only advance watermark on send
    success.
  - Healthchecks.io: ping /start at top, /fail on exception, / (success) at end.
"""
from __future__ import annotations

import os
import sys
import traceback
import zoneinfo
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from hyacine.config import Settings, YamlConfig, load_yaml_config
from hyacine.db import Run, Watermark, init_db, session_scope
from hyacine.i18n import weekday_label
from hyacine.llm import summarize
from hyacine.llm.providers import resolve as resolve_provider
from hyacine.models import FetchResult, RunRecord, RunStatus

# Display labels for the supported language codes. Only used to append a
# natural-language instruction to the LLM user message — the system prompt
# itself is user-owned.
_LANGUAGE_LABELS = {
    "en": "English",
    "zh-CN": "Simplified Chinese (zh-CN / 简体中文)",
    "zh-TW": "Traditional Chinese (zh-TW / 繁體中文)",
    "ja": "Japanese (日本語)",
}

ProgressCallback = Callable[[str, str], None]

# Module-level settings singletons — overridable for tests via monkeypatch
_settings: Settings | None = None
_cfg: YamlConfig | None = None


def _get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def _get_cfg() -> YamlConfig:
    global _cfg
    if _cfg is None:
        _cfg = load_yaml_config(_get_settings().config_path)
    return _cfg


_WATERMARK_KEY = "last_successful_run_at"


def read_watermark() -> datetime:
    """Return last_successful_run_at (UTC). Backfill to now-24h on first run."""
    settings = _get_settings()
    cfg = _get_cfg()
    init_db(settings.db_path)

    with session_scope(settings.db_path) as session:
        row = session.get(Watermark, _WATERMARK_KEY)
        if row is not None:
            dt = datetime.fromisoformat(row.value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt

    backfill = datetime.now(UTC) - timedelta(hours=cfg.initial_watermark_lookback_hours)
    with session_scope(settings.db_path, write=True) as session:
        row = session.get(Watermark, _WATERMARK_KEY)
        if row is None:
            session.add(
                Watermark(
                    key=_WATERMARK_KEY,
                    value=backfill.isoformat(),
                    updated_at=datetime.now(UTC),
                )
            )
    return backfill


def advance_watermark(new_value_utc: datetime) -> None:
    """Persist last_successful_run_at atomically (BEGIN IMMEDIATE)."""
    settings = _get_settings()
    with session_scope(settings.db_path, write=True) as session:
        row = session.get(Watermark, _WATERMARK_KEY)
        now = datetime.now(UTC)
        if row is None:
            session.add(
                Watermark(
                    key=_WATERMARK_KEY,
                    value=new_value_utc.isoformat(),
                    updated_at=now,
                )
            )
        else:
            row.value = new_value_utc.isoformat()
            row.updated_at = now


def run_pipeline(
    now_utc: datetime | None = None,
    *,
    dry_run: bool = False,
    progress: ProgressCallback | None = None,
) -> RunRecord:
    """Run one full pipeline iteration.

    ``now_utc`` override is for tests; production path passes None.
    ``dry_run=True`` skips the actual sendMail call (and the watermark
    advance) so callers like the desktop wizard's preview step can see the
    rendered output without inboxing anyone.
    ``progress`` — optional callback invoked as ``(stage, status)`` at each
    stage boundary. ``stage`` ∈ {fetch, classify, llm, render, deliver};
    ``status`` ∈ {running, ok, fail}. A no-op default means existing CLI
    / test callers need no change.
    """
    from hyacine.graph.auth import load_or_create_record
    from hyacine.graph.fetch import fetch_calendar, fetch_emails
    from hyacine.graph.send import send_email
    from hyacine.pipeline.rules import RuleSet, load_rules

    def _p(stage: str, status: str) -> None:
        if progress is not None:
            try:
                progress(stage, status)
            except Exception:  # noqa: BLE001
                pass  # never let a misbehaving frontend hook break the pipeline

    settings = _get_settings()
    cfg = _get_cfg()

    if not cfg.recipient_email:
        raise ValueError(
            "recipient_email is not configured. "
            "Run `python -m hyacine init` to set up your configuration."
        )

    init_db(settings.db_path)

    now_utc = now_utc or datetime.now(UTC)
    local_tz = zoneinfo.ZoneInfo(cfg.timezone)
    now_local = now_utc.astimezone(local_tz)

    watermark = read_watermark()

    with session_scope(settings.db_path, write=True) as session:
        run_row = Run(
            started_at=now_utc,
            finished_at=None,
            status=RunStatus.RUNNING,
            window_from=watermark,
            window_to=now_utc,
            email_count=0,
        )
        session.add(run_row)
        session.flush()
        run_id = run_row.id

    def _update_row(**kwargs: object) -> None:
        with session_scope(settings.db_path, write=True) as s:
            row = s.get(Run, run_id)
            if row is not None:
                for k, v in kwargs.items():
                    setattr(row, k, v)

    def _load_record() -> RunRecord:
        with session_scope(settings.db_path) as s:
            row = s.get(Run, run_id)
            assert row is not None
            return RunRecord(
                id=row.id,
                started_at=_ensure_utc(row.started_at),
                finished_at=_ensure_utc(row.finished_at) if row.finished_at else None,
                status=RunStatus(row.status),
                window_from=_ensure_utc(row.window_from),
                window_to=_ensure_utc(row.window_to),
                email_count=row.email_count,
                markdown=row.markdown,
                error_traceback=row.error_traceback,
                sent_message_id=row.sent_message_id,
            )

    try:
        from hyacine.ops.monitoring import ping_healthchecks
        ping_healthchecks(settings.healthchecks_uuid, "start", "")
    except Exception:
        pass

    emails = []
    calendar = []
    markdown: str | None = None
    sent_message_id: str | None = None
    fetch_error: Exception | None = None
    llm_error: Exception | None = None
    send_error: Exception | None = None

    # --- Phase 1: Fetch ---
    _p("fetch", "running")
    try:
        cred, _ = load_or_create_record(
            settings.graph_client_id,
            settings.graph_tenant_id,
            settings.auth_dir,
            settings.scope_list,
        )
        emails = fetch_emails(cred, watermark, now_utc)
        calendar = fetch_calendar(cred, now_local.date(), timezone_name=cfg.timezone)
    except Exception as exc:
        fetch_error = exc
        tb = traceback.format_exc()
        _update_row(
            status=RunStatus.FAILED,
            finished_at=datetime.now(UTC),
            error_traceback=tb,
        )
        _p("fetch", "fail")
        try:
            from hyacine.ops.monitoring import ping_healthchecks
            ping_healthchecks(settings.healthchecks_uuid, "fail", tb)
        except Exception:
            pass
        return _load_record()
    _p("fetch", "ok")

    # --- Phase 2: Classify ---
    _p("classify", "running")
    ruleset: RuleSet | None = None
    try:
        ruleset = load_rules(settings.rules_path)
    except Exception as exc:
        # Non-fatal: classify without rules, but say why (one line; YAML and
        # validation errors are multi-line, so collapse the whitespace).
        reason = " ".join(f"{exc.__class__.__name__}: {exc}".split())
        print(f"WARN: rules not loaded, classifying without them: {reason}", file=sys.stderr)

    for email in emails:
        if ruleset is not None:
            email.category_hint = ruleset.classify(email)
    _p("classify", "ok")

    # --- Phase 3: LLM ---
    _p("llm", "running")
    fetch_result = FetchResult(
        window_from=watermark,
        window_to=now_utc,
        emails=emails,
        calendar_today=calendar,
        generated_at=now_utc,
    )
    json_input = fetch_result.to_llm_json()

    # Append a language instruction so the output obeys the user's config
    # even when their system prompt doesn't mention a language explicitly.
    # The prompt file is user-owned and often doesn't know about this
    # setting; the instruction belongs on the user turn so we never
    # silently edit a file the user can inspect.
    lang_label = _LANGUAGE_LABELS.get(cfg.language, cfg.language or "English")
    user_message = (
        "Generate the daily report from the JSON on stdin. "
        f"Respond in {lang_label}."
    )

    try:
        # Build the active provider from config. resolve() handles three
        # cases uniformly: built-in preset by id, custom-endpoint
        # (llm_api_format + llm_base_url in config), and stale/unknown id
        # (falls back to the default preset).
        provider = resolve_provider(
            provider_id=cfg.llm_provider,
            api_format=cfg.llm_api_format,
            base_url=cfg.llm_base_url,
            model=cfg.llm_model,
        )
        # Providers that authenticate via an API key expect the secret in
        # `HYACINE_LLM_API_KEY` (the Rust parent populates this from the
        # keychain slot matching the active provider). The CLI provider
        # uses its own env conventions (CLAUDE_CODE_OAUTH_TOKEN) handled
        # inside claude_code.summarize.
        api_key = os.environ.get("HYACINE_LLM_API_KEY", "")
        markdown = summarize(
            json_input,
            settings.prompt_path,
            provider=provider,
            api_key=api_key,
            model=cfg.llm_model,
            timeout_seconds=cfg.llm_timeout_seconds,
            user_message=user_message,
        )
    except Exception as exc:
        llm_error = exc
        tb = traceback.format_exc()
        _update_row(
            status=RunStatus.FAILED,
            finished_at=datetime.now(UTC),
            email_count=len(emails),
            error_traceback=tb,
        )
        _p("llm", "fail")
        try:
            from hyacine.ops.monitoring import ping_healthchecks
            ping_healthchecks(settings.healthchecks_uuid, "fail", tb)
        except Exception:
            pass
        return _load_record()
    _p("llm", "ok")

    # --- Phase 4: Render ---
    # "Render" in this pipeline is the moment we commit to the LLM's
    # markdown output as the final payload to ship (markdown → HTML
    # happens inside `send_email` or the dry-run caller; neither can
    # fail in isolation). We emit running/ok back-to-back so the wizard
    # UI shows a distinct step that resolves only after the LLM has
    # produced usable text — not pre-emptively alongside LLM ok.
    _p("render", "running")
    subject = f"Hyacine · {now_local.strftime('%Y-%m-%d')}"
    render_weekday = weekday_label(now_local, cfg.language)
    render_date = now_local.strftime("%Y-%m-%d")
    render_time = now_local.strftime("%H:%M")
    _p("render", "ok")

    # --- Phase 5: Send (skipped in dry-run) ---
    _p("deliver", "running")
    if dry_run:
        # Wizard preview path: render the email but DO NOT call sendMail.
        # We also leave the watermark untouched so the next real run still
        # picks up the same window — a dry-run must be idempotent.
        sent_message_id = "(dry-run)"
        _update_row(
            status=RunStatus.SUCCESS,
            finished_at=datetime.now(UTC),
            email_count=len(emails),
            markdown=markdown,
            sent_message_id=sent_message_id,
        )
        _p("deliver", "ok")
        return _load_record()

    try:
        sent_message_id = send_email(
            cred,
            cfg.recipient_email,
            subject,
            markdown,
            model=cfg.llm_model,
            date=render_date,
            weekday=render_weekday,
            generated_at=render_time,
            language=cfg.language,
        )
    except Exception as exc:
        send_error = exc
        tb = traceback.format_exc()
        # A SIGTERM that lands mid-POST leaves the outcome as open as a read
        # timeout does.
        uncertain = _delivery_uncertain(exc) or isinstance(exc, RunTerminated)
        if uncertain:
            # Shown under the traceback on the dashboard's run page.
            tb += f"{_DELIVERY_UNKNOWN_NOTE}\n"
        try:
            _update_row(
                status=RunStatus.FAILED,
                finished_at=datetime.now(UTC),
                email_count=len(emails),
                markdown=markdown,
                error_traceback=tb,
            )
            failed_record = _load_record()
        except Exception as record_exc:
            if not uncertain:
                raise
            # Same rule as the success path: a bookkeeping error must not turn
            # "may have been sent" into a retryable failure.
            raise DeliveredButNotRecorded(None, outcome_unknown=True) from record_exc
        _p("deliver", "fail")
        try:
            from hyacine.ops.monitoring import ping_healthchecks
            ping_healthchecks(settings.healthchecks_uuid, "fail", tb)
        except Exception:
            pass
        return failed_record.model_copy(update={"delivery_uncertain": uncertain})

    # --- Success path ---
    # The digest is in the inbox from here on. If recording that fails, raise
    # a distinct error so main() keeps systemd from re-running (re-sending).
    watermark_advanced = False
    try:
        advance_watermark(now_utc)
        watermark_advanced = True
        _update_row(
            status=RunStatus.SUCCESS,
            finished_at=datetime.now(UTC),
            email_count=len(emails),
            markdown=markdown,
            sent_message_id=sent_message_id,
        )
    except Exception as exc:
        raise DeliveredButNotRecorded(
            sent_message_id, watermark_advanced=watermark_advanced
        ) from exc
    _p("deliver", "ok")

    try:
        from hyacine.ops.monitoring import ping_healthchecks
        ping_healthchecks(settings.healthchecks_uuid, "success", "")
    except Exception:
        pass

    _ = fetch_error, llm_error, send_error

    return _load_record()


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


# Appended to a FAILED run's stored traceback when _delivery_uncertain().
_DELIVERY_UNKNOWN_NOTE = "delivery outcome unknown: not retrying"


def _delivery_uncertain(exc: BaseException) -> bool:
    """True when sendMail raised but Graph may still have accepted the message.

    Mirrors the POST retry policy in :mod:`hyacine.graph._http`: a 5xx other
    than 503, or a transport error after the request went out (ReadTimeout,
    ReadError, RemoteProtocolError, ...), leaves the outcome unknown, and
    re-running the pipeline could mail a second digest. Everything else is
    safe to retry: 4xx (incl. 429) and 503 are refusals, connect / pool
    errors never reached Graph, and token or render errors are raised
    before the POST.
    """
    import httpx

    from hyacine.graph._http import GraphHTTPError

    if isinstance(exc, GraphHTTPError):
        status = exc.response.status_code
        return status >= 500 and status != 503
    if isinstance(exc, httpx.TransportError):
        return not isinstance(
            exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
        )
    return False


def _exception_summary(tb: str) -> str:
    """One-line ``Class: message`` of the final exception in a traceback.

    The last line alone is not enough: multi-line messages (azure-identity's
    AADSTS errors, for one) put the useful part first. So take every line
    after the last ``  File ...`` frame and its indented source / caret
    lines, whitespace-collapsed. Text without frames is collapsed whole.
    """
    lines = tb.strip().splitlines()
    start = 0
    for i, line in enumerate(lines):
        if line.startswith("  File "):
            start = i + 1
    while start < len(lines) and lines[start].startswith("    "):
        start += 1
    return " ".join(" ".join(lines[start:]).split())


def _alert_failure(summary: str) -> None:
    """Best-effort ntfy alert for a failed run. Never raises.

    ntfy topics are readable by anyone who knows the name, so only a short
    one-line summary goes out; the full traceback stays in the run row and
    journald. No-op when HYACINE_NTFY_TOPIC is unset (send_ntfy skips an
    empty topic).
    """
    try:
        from hyacine.ops.monitoring import send_ntfy

        message = " ".join(summary.split())[:200]  # one line, short
        send_ntfy(_get_settings().ntfy_topic, message, title="hyacine run failed")
    except Exception:  # noqa: BLE001
        pass  # the alert path must never turn a failed run into a crash


# Exit status for a failure that must not be retried: the digest may already
# be in the inbox. hyacine-run.service lists it in RestartPreventExitStatus=.
EXIT_NO_RETRY = 3


class DeliveredButNotRecorded(Exception):
    """sendMail succeeded (or may have), then recording the run failed.

    Raised from the original error, either after a successful send (advancing
    the watermark or writing the SUCCESS row failed) or after a send whose
    outcome is unknown (writing the FAILED row failed; ``outcome_unknown``).
    main() exits EXIT_NO_RETRY: a retry could mail the same digest again.
    """

    def __init__(
        self,
        sent_message_id: str | None,
        *,
        watermark_advanced: bool = False,
        outcome_unknown: bool = False,
    ) -> None:
        self.sent_message_id = sent_message_id
        self.watermark_advanced = watermark_advanced
        self.outcome_unknown = outcome_unknown
        what = (
            "sendMail outcome unknown"
            if outcome_unknown
            else f"digest sent (sent_message_id={sent_message_id})"
        )
        super().__init__(
            f"{what} but the run was not recorded; "
            f"watermark {'advanced' if watermark_advanced else 'not advanced'}"
        )


class RunTerminated(Exception):
    """Raised by main()'s SIGTERM handler.

    An ``Exception`` on purpose: the phase handlers in :func:`run_pipeline`
    catch it like any other failure and mark the run FAILED.
    """


def _on_sigterm(signum: int, frame: object) -> None:
    raise RunTerminated("terminated by SIGTERM (systemd TimeoutStartSec or stop)")


def main() -> int:
    """CLI entry: `python -m hyacine.pipeline.run` or `python -m hyacine run`.

    Exit status: 0 sent, 1 failed (systemd retries), EXIT_NO_RETRY when the
    digest may already be in the inbox.
    """
    import signal

    # systemd stops a run with SIGTERM (TimeoutStartSec, `systemctl stop`).
    # Dying on the spot would leave the run row RUNNING forever; raising lets
    # the phase in progress record it as FAILED and alert. subprocess.run
    # kills its child (the claude CLI) on the way out.
    previous_sigterm = signal.signal(signal.SIGTERM, _on_sigterm)
    try:
        record = run_pipeline()
        if record.status == RunStatus.SUCCESS:
            print(f"OK: sent={record.sent_message_id} emails={record.email_count}")
            return 0
        summary = "PipelineError"
        if record.error_traceback:
            summary = _exception_summary(record.error_traceback) or summary
        if record.delivery_uncertain:
            # The note run_pipeline appended for the dashboard ends the
            # summary; both lines below say it in their own words.
            cause = summary.removesuffix(_DELIVERY_UNKNOWN_NOTE).rstrip()
            print(f"FAIL: {cause} ({_DELIVERY_UNKNOWN_NOTE})")
            _alert_failure(
                f"run {record.id} failed: sendMail outcome unknown, not retrying - "
                f"check the inbox ({cause})"
            )
            return EXIT_NO_RETRY
        print(f"FAIL: {summary}")
        _alert_failure(f"run {record.id} failed: {summary}")
        return 1
    except DeliveredButNotRecorded as exc:
        traceback.print_exc()
        original = exc.__cause__
        reason = f"{original.__class__.__name__}: {original}" if original else "unknown error"
        print(f"FAIL: {exc}: {reason}")
        state = "advanced" if exc.watermark_advanced else "not advanced"
        if exc.outcome_unknown:
            _alert_failure(
                "sendMail outcome unknown and the run was not recorded, not retrying - "
                f"check the inbox ({reason})"
            )
        else:
            _alert_failure(
                f"digest sent but the run was not recorded; watermark {state} ({reason})"
            )
        return EXIT_NO_RETRY
    except Exception as exc:
        # Full traceback to stderr (journald under systemd); stdout and the
        # alert get the one-line summary.
        traceback.print_exc()
        summary = f"{exc.__class__.__name__}: {exc}"
        print(f"FAIL: {summary}")
        _alert_failure(f"run failed: {summary}")
        return 1
    finally:
        if previous_sigterm is not None:  # None: set outside Python, can't restore
            signal.signal(signal.SIGTERM, previous_sigterm)


if __name__ == "__main__":
    raise SystemExit(main())
