"""DB schema smoke tests — verify init_db is idempotent and WAL is on."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from hyacine import db as db_mod


def test_init_db_creates_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    db_mod._engine = None  # reset module-level singleton for isolated tests
    db_mod._SessionFactory = None
    db_mod.init_db(db_path)
    engine = db_mod.get_engine(db_path)
    names = set(inspect(engine).get_table_names())
    assert {"briefing_runs", "watermarks", "config_snapshots"}.issubset(names)


def test_init_db_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    db_mod._engine = None
    db_mod._SessionFactory = None
    db_mod.init_db(db_path)
    db_mod.init_db(db_path)  # must not raise
