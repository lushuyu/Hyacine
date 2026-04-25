"""Web UI tests — uses FastAPI TestClient with a tmp_path DB and content files."""
from __future__ import annotations

from collections.abc import Generator
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
