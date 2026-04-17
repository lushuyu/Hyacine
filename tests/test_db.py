"""DB schema smoke tests — verify init_db is idempotent and WAL is on."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import inspect

from hyacine import db as db_mod


def _reset_engine() -> None:
    db_mod._engine = None
    db_mod._SessionFactory = None


def test_init_db_creates_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    _reset_engine()
    db_mod.init_db(db_path)
    engine = db_mod.get_engine(db_path)
    names = set(inspect(engine).get_table_names())
    assert {"runs", "watermarks", "config_snapshots"}.issubset(names)


def test_init_db_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    _reset_engine()
    db_mod.init_db(db_path)
    db_mod.init_db(db_path)  # must not raise


def test_legacy_schema_migration_is_idempotent(tmp_path: Path) -> None:
    """Second call (simulating a concurrent startup) must not raise."""
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE briefing_runs (id INTEGER PRIMARY KEY, briefing_markdown TEXT)"
        )
        conn.commit()

    db_mod._migrate_legacy_schema(db_path)

    with sqlite3.connect(db_path) as conn:
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
    assert "runs" in tables
    assert "briefing_runs" not in tables
    assert "markdown" in cols
    assert "briefing_markdown" not in cols

    db_mod._migrate_legacy_schema(db_path)  # already migrated → no-op


def test_legacy_file_migration_second_call_is_noop(tmp_path: Path) -> None:
    """If the legacy file was already renamed, a second call must not raise."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    legacy = data_dir / "briefing.db"
    legacy.write_bytes(b"")
    target = data_dir / "hyacine.db"

    db_mod._migrate_legacy_file(target)
    assert target.exists()
    assert not legacy.exists()

    db_mod._migrate_legacy_file(target)  # both branches are no-ops now
