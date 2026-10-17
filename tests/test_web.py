"""Web UI tests — uses FastAPI TestClient with a tmp_path DB and content files."""
from __future__ import annotations

import subprocess
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import hyacine.db as db_module


def _utcnow() -> datetime:
    return datetime.now(tz=UTC).replace(tzinfo=None)


def _make_app(tmp_path: Path) -> TestClient:
    """Create a fresh app pointed at tmp_path, resetting the global engine cache."""
    db_module._engine = None
    db_module._SessionFactory = None

    db_path = tmp_path / "test.db"
    prompt_path = tmp_path / "hyacine.md"
    rules_path = tmp_path / "rules.yaml"
    config_path = tmp_path / "config.yaml"

    prompt_path.write_text("", encoding="utf-8")
    rules_path.write_text("rules: []\n", encoding="utf-8")

    import importlib  # noqa: PLC0415
    import os  # noqa: PLC0415

    os.environ["HYACINE_DB_PATH"] = str(db_path)
    os.environ["HYACINE_PROMPT_PATH"] = str(prompt_path)
    os.environ["HYACINE_RULES_PATH"] = str(rules_path)
    os.environ["HYACINE_CONFIG_PATH"] = str(config_path)

    import hyacine.config as cfg_mod  # noqa: PLC0415

    importlib.reload(cfg_mod)

    import hyacine.web.utils as utils_mod  # noqa: PLC0415

    importlib.reload(utils_mod)

    import hyacine.web.routes.actions as act_mod  # noqa: PLC0415
    import hyacine.web.routes.dashboard as dash_mod  # noqa: PLC0415
    import hyacine.web.routes.prompt as pr_mod  # noqa: PLC0415
    import hyacine.web.routes.rules as rl_mod  # noqa: PLC0415
    import hyacine.web.routes.runs as runs_mod  # noqa: PLC0415

    importlib.reload(dash_mod)
    importlib.reload(runs_mod)
    importlib.reload(act_mod)
    importlib.reload(pr_mod)
    importlib.reload(rl_mod)

    import hyacine.web.app as app_mod  # noqa: PLC0415

    importlib.reload(app_mod)

    templates_dir = Path(__file__).parent.parent / "src" / "hyacine" / "web" / "templates"
    app = app_mod.create_app(templates_dir=templates_dir)

    db_module.init_db(db_path)

    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    tc = _make_app(tmp_path)
    with tc:
        yield tc


@pytest.fixture()
def client_with_db(tmp_path: Path) -> Generator[tuple[TestClient, Path], None, None]:
    tc = _make_app(tmp_path)
    db_path = tmp_path / "test.db"
    with tc:
        yield tc, db_path


# ---------------------------------------------------------------------------
# Dashboard tests
# ---------------------------------------------------------------------------

def test_dashboard_empty_db_renders_200(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "No runs yet" in resp.text


def test_dashboard_lists_runs(client_with_db: tuple[TestClient, Path]) -> None:
    tc, db_path = client_with_db

    with db_module.session_scope(db_path, write=True) as session:
        session.add(db_module.Run(
            started_at=datetime(2024, 1, 15, 8, 0, 0),
            finished_at=datetime(2024, 1, 15, 8, 1, 0),
            status="success",
            window_from=datetime(2024, 1, 14, 0, 0, 0),
            window_to=datetime(2024, 1, 15, 0, 0, 0),
            email_count=5,
        ))
        session.add(db_module.Run(
            started_at=datetime(2024, 1, 16, 8, 0, 0),
            finished_at=datetime(2024, 1, 16, 8, 1, 0),
            status="failed",
            window_from=datetime(2024, 1, 15, 0, 0, 0),
            window_to=datetime(2024, 1, 16, 0, 0, 0),
            email_count=0,
        ))

    resp = tc.get("/")
    assert resp.status_code == 200
    assert "success" in resp.text
    assert "failed" in resp.text


# ---------------------------------------------------------------------------
# Run detail tests
# ---------------------------------------------------------------------------

def test_run_detail_renders_markdown(client_with_db: tuple[TestClient, Path]) -> None:
    tc, db_path = client_with_db

    with db_module.session_scope(db_path, write=True) as session:
        run = db_module.Run(
            started_at=_utcnow(),
            status="success",
            window_from=_utcnow(),
            window_to=_utcnow(),
            email_count=0,
            markdown="# hi",
        )
        session.add(run)
        session.flush()
        run_id = run.id

    resp = tc.get(f"/runs/{run_id}")
    assert resp.status_code == 200
    # Markdown "# hi" round-trips through the modern email shell into a
    # styled <h1>...hi</h1> — accept any inline-styled variant.
    assert "<h1" in resp.text
    assert ">hi</h1>" in resp.text


def test_run_detail_404(client: TestClient) -> None:
    resp = client.get("/runs/99999")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Prompt editor tests
# ---------------------------------------------------------------------------

def test_prompt_get_returns_current_text(tmp_path: Path) -> None:
    tc = _make_app(tmp_path)
    prompt_path = tmp_path / "hyacine.md"
    prompt_path.write_text("SYS", encoding="utf-8")

    with tc:
        resp = tc.get("/prompt")
    assert resp.status_code == 200
    assert "SYS" in resp.text


def test_prompt_post_valid_persists_and_snapshots(tmp_path: Path) -> None:
    tc = _make_app(tmp_path)
    prompt_path = tmp_path / "hyacine.md"
    db_path = tmp_path / "test.db"
    new_content = "Hello {{ name }}"

    with tc:
        resp = tc.post("/prompt", data={"content": new_content}, follow_redirects=False)

    assert resp.status_code == 303
    assert prompt_path.read_text(encoding="utf-8") == new_content

    with db_module.session_scope(db_path) as session:
        snapshots = session.execute(
            select(db_module.ConfigSnapshotRow).where(
                db_module.ConfigSnapshotRow.kind == "prompt"
            )
        ).scalars().all()
    assert len(snapshots) == 1
    assert snapshots[0].content == new_content


def test_prompt_post_invalid_jinja_422(client: TestClient) -> None:
    resp = client.post("/prompt", data={"content": "{% blah"})
    assert resp.status_code == 422
    assert "error" in resp.text.lower() or "Validation" in resp.text or "blah" in resp.text or "unexpected" in resp.text.lower()


# ---------------------------------------------------------------------------
# Rules editor tests
# ---------------------------------------------------------------------------

def test_rules_post_valid(tmp_path: Path) -> None:
    tc = _make_app(tmp_path)
    rules_path = tmp_path / "rules.yaml"
    db_path = tmp_path / "test.db"
    valid_yaml = "rules:\n  - name: test\n    category: arxiv\n    sender_domain: arxiv.org\n"

    with tc:
        resp = tc.post("/rules", data={"content": valid_yaml}, follow_redirects=False)

    assert resp.status_code == 303
    assert rules_path.read_text(encoding="utf-8") == valid_yaml

    with db_module.session_scope(db_path) as session:
        snapshots = session.execute(
            select(db_module.ConfigSnapshotRow).where(
                db_module.ConfigSnapshotRow.kind == "rules"
            )
        ).scalars().all()
    assert len(snapshots) == 1


def test_rules_post_invalid_422(client: TestClient) -> None:
    resp = client.post("/rules", data={"content": "not: valid: yaml: garbage: ["})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Actions test
# ---------------------------------------------------------------------------

def test_actions_run_falls_back_when_systemctl_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tc = _make_app(tmp_path)

    popen_calls: list[list[str]] = []

    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise FileNotFoundError("systemctl not found")

    class FakePopen:
        def __init__(self, cmd: list[str], **kwargs: object) -> None:
            popen_calls.append(cmd)

    import hyacine.web.routes.actions as actions_mod
    monkeypatch.setattr(actions_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(actions_mod.subprocess, "Popen", FakePopen)

    with tc:
        resp = tc.post("/actions/run")

    assert resp.status_code == 200
    assert "subprocess" in resp.text
    assert len(popen_calls) == 1
    assert popen_calls[0][0].endswith("python") or "python" in popen_calls[0][0]
    assert "-m" in popen_calls[0]
    assert "hyacine.pipeline.run" in popen_calls[0]


def _patch_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    run_impl: Callable[[list[str]], subprocess.CompletedProcess[bytes]],
) -> tuple[list[list[str]], list[list[str]]]:
    """Swap subprocess.run/Popen in actions.py; return (run_calls, popen_calls)."""
    run_calls: list[list[str]] = []
    popen_calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        run_calls.append(cmd)
        return run_impl(cmd)

    class FakePopen:
        def __init__(self, cmd: list[str], **kwargs: object) -> None:
            popen_calls.append(cmd)

    import hyacine.web.routes.actions as actions_mod
    monkeypatch.setattr(actions_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(actions_mod.subprocess, "Popen", FakePopen)
    return run_calls, popen_calls


def test_actions_run_queues_via_systemd_without_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tc = _make_app(tmp_path)
    run_calls, popen_calls = _patch_subprocess(
        monkeypatch, lambda cmd: subprocess.CompletedProcess(cmd, 0)
    )

    with tc:
        resp = tc.post("/actions/run")

    assert resp.status_code == 200
    assert "Queued (systemd)" in resp.text
    assert resp.headers["HX-Trigger"] == "runQueued"
    # hyacine-run.service is Type=oneshot: without --no-block, start waits for
    # the whole run and trips the 10 s timeout.
    assert run_calls == [
        ["systemctl", "--user", "start", "--no-block", "hyacine-run.service"]
    ]
    assert popen_calls == []


def test_actions_run_timeout_does_not_spawn_second_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tc = _make_app(tmp_path)

    def timeout(cmd: list[str]) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd, 10)

    run_calls, popen_calls = _patch_subprocess(monkeypatch, timeout)

    with tc:
        resp = tc.post("/actions/run")

    assert resp.status_code == 200
    assert len(run_calls) == 1
    assert popen_calls == []
    assert "Queued" not in resp.text
    assert "systemctl --user status hyacine-run.service" in resp.text
    assert "HX-Trigger" not in resp.headers


def test_actions_run_nonzero_exit_falls_back_to_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tc = _make_app(tmp_path)
    # e.g. "Failed to connect to bus" (1) or "Unit ... not found" (5).
    run_calls, popen_calls = _patch_subprocess(
        monkeypatch, lambda cmd: subprocess.CompletedProcess(cmd, 5)
    )

    with tc:
        resp = tc.post("/actions/run")

    assert resp.status_code == 200
    assert "Queued (subprocess)" in resp.text
    assert len(run_calls) == 1
    assert len(popen_calls) == 1
    assert "hyacine.pipeline.run" in popen_calls[0]


# ---------------------------------------------------------------------------
# Cross-site write protection
# ---------------------------------------------------------------------------

_CROSS_SITE_HEADERS = [
    pytest.param({"Sec-Fetch-Site": "cross-site"}, id="fetch-site-cross-site"),
    # Another port on localhost is same-site but not same-origin.
    pytest.param({"Sec-Fetch-Site": "same-site"}, id="fetch-site-same-site"),
    # Sec-Fetch-Site takes precedence over a matching Origin.
    pytest.param(
        {"Sec-Fetch-Site": "cross-site", "Origin": "http://testserver"},
        id="fetch-site-beats-origin",
    ),
    pytest.param({"Origin": "https://evil.example"}, id="foreign-origin"),
    pytest.param({"Origin": "http://testserver:9999"}, id="origin-other-port"),
    pytest.param({"Origin": "null"}, id="null-origin"),
]

_EDITOR_POSTS = [
    pytest.param("/prompt", "hyacine.md", "prompt", "Ignore all rules.", id="prompt"),
    pytest.param(
        "/rules",
        "rules.yaml",
        "rules",
        "rules:\n  - name: evil\n    category: arxiv\n    sender_domain: evil.example\n",
        id="rules",
    ),
]


def _snapshot_count(db_path: Path, kind: str) -> int:
    with db_module.session_scope(db_path) as session:
        rows = session.execute(
            select(db_module.ConfigSnapshotRow).where(db_module.ConfigSnapshotRow.kind == kind)
        ).scalars().all()
    return len(rows)


@pytest.mark.parametrize("headers", _CROSS_SITE_HEADERS)
@pytest.mark.parametrize(("endpoint", "filename", "kind", "content"), _EDITOR_POSTS)
def test_cross_site_editor_post_is_rejected(
    tmp_path: Path,
    endpoint: str,
    filename: str,
    kind: str,
    content: str,
    headers: dict[str, str],
) -> None:
    tc = _make_app(tmp_path)
    target = tmp_path / filename
    before = target.read_text(encoding="utf-8")

    with tc:
        resp = tc.post(
            endpoint, data={"content": content}, headers=headers, follow_redirects=False
        )

    assert resp.status_code == 403
    assert target.read_text(encoding="utf-8") == before
    assert _snapshot_count(tmp_path / "test.db", kind) == 0


@pytest.mark.parametrize("headers", _CROSS_SITE_HEADERS)
def test_cross_site_run_post_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, headers: dict[str, str]
) -> None:
    tc = _make_app(tmp_path)
    run_calls, popen_calls = _patch_subprocess(
        monkeypatch, lambda cmd: subprocess.CompletedProcess(cmd, 0)
    )

    with tc:
        resp = tc.post("/actions/run", headers=headers)

    assert resp.status_code == 403
    assert run_calls == []
    assert popen_calls == []


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="no-headers"),
        # What htmx in a current browser sends from the UI itself.
        pytest.param(
            {"Sec-Fetch-Site": "same-origin", "Origin": "http://testserver", "HX-Request": "true"},
            id="htmx-same-origin",
        ),
        pytest.param({"Origin": "http://testserver"}, id="matching-origin-only"),
        pytest.param({"Sec-Fetch-Site": "none"}, id="fetch-site-none"),
    ],
)
@pytest.mark.parametrize(("endpoint", "filename", "kind", "content"), _EDITOR_POSTS)
def test_same_origin_editor_post_is_accepted(
    tmp_path: Path,
    endpoint: str,
    filename: str,
    kind: str,
    content: str,
    headers: dict[str, str],
) -> None:
    tc = _make_app(tmp_path)

    with tc:
        resp = tc.post(
            endpoint, data={"content": content}, headers=headers, follow_redirects=False
        )

    assert resp.status_code == 303
    assert (tmp_path / filename).read_text(encoding="utf-8") == content
    assert _snapshot_count(tmp_path / "test.db", kind) == 1


def test_same_origin_run_post_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tc = _make_app(tmp_path)
    run_calls, _ = _patch_subprocess(
        monkeypatch, lambda cmd: subprocess.CompletedProcess(cmd, 0)
    )

    with tc:
        resp = tc.post(
            "/actions/run",
            headers={"Sec-Fetch-Site": "same-origin", "Origin": "http://testserver"},
        )

    assert resp.status_code == 200
    assert "Queued (systemd)" in resp.text
    assert len(run_calls) == 1


@pytest.mark.parametrize("path", ["/", "/prompt", "/rules"])
def test_cross_site_get_is_unaffected(client: TestClient, path: str) -> None:
    resp = client.get(
        path, headers={"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"}
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Opt-in Host pinning (HYACINE_WEB_ALLOWED_HOSTS)
# ---------------------------------------------------------------------------

def test_any_host_accepted_when_allowed_hosts_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HYACINE_WEB_ALLOWED_HOSTS", raising=False)
    tc = _make_app(tmp_path)

    with tc:
        resp = tc.get("/", headers={"Host": "box.tailnet.ts.net:8765"})

    assert resp.status_code == 200


def test_allowed_hosts_env_pins_host_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HYACINE_WEB_ALLOWED_HOSTS", " Box.tailnet.ts.net , ")
    tc = _make_app(tmp_path)

    with tc:
        rebound = tc.get("/", headers={"Host": "attacker.example"})
        listed = tc.get("/", headers={"Host": "box.tailnet.ts.net:8765"})
        loopback_ip = tc.get("/", headers={"Host": "127.0.0.1:8765"})
        loopback_name = tc.get("/", headers={"Host": "localhost:8765"})

    assert rebound.status_code == 400
    assert listed.status_code == 200
    assert loopback_ip.status_code == 200
    assert loopback_name.status_code == 200
