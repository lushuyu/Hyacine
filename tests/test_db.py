"""DB schema smoke tests — verify init_db is idempotent and WAL is on."""
from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest
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


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits only")
def test_init_db_tightens_permissions(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "hyacine.db"
    _reset_engine()
    db_mod.init_db(db_path)

    parent_mode = stat.S_IMODE(db_path.parent.stat().st_mode)
    assert parent_mode == 0o700, f"expected dir 0700, got {oct(parent_mode)}"

    db_mode = stat.S_IMODE(db_path.stat().st_mode)
    assert db_mode == 0o600, f"expected db 0600, got {oct(db_mode)}"
