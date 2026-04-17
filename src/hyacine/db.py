"""SQLAlchemy 2.0 schema — sync engine, WAL mode, single-writer.

Three tables:
  runs             — one row per pipeline attempt (success or failure)
  watermarks       — key/value; holds `last_successful_run_at` (UTC ISO)
  config_snapshots — versioned prompt/rules edits for rollback

Uses BEGIN IMMEDIATE for writes to keep the single-writer invariant under
systemd-launched runs + the web process.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    DateTime,
    Engine,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    window_from: Mapped[datetime] = mapped_column(DateTime)
    window_to: Mapped[datetime] = mapped_column(DateTime)
    email_count: Mapped[int] = mapped_column(Integer, default=0)
    markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    hc_ping_result: Mapped[str] = mapped_column(String(16), default="skipped")
    sent_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Watermark(Base):
    __tablename__ = "watermarks"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class ConfigSnapshotRow(Base):
    __tablename__ = "config_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    content: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text, default="")


_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def _apply_pragmas(dbapi_conn, _connection_record) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_engine(db_path: Path) -> Engine:
    global _engine, _SessionFactory
    if _engine is not None:
        return _engine
    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{db_path}"
    _engine = create_engine(url, future=True)
    event.listen(_engine, "connect", _apply_pragmas)
    _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def _migrate_legacy_file(db_path: Path) -> None:
    """If legacy ./data/briefing.db exists and the target doesn't, move it.

    Safe under concurrent startup (web + run service): if another process
    renamed the file between our exists() check and our rename() call, we
    swallow the error and let the other caller finish the migration.
    """
    if db_path.exists():
        return
    legacy = db_path.parent / "briefing.db"
    if not legacy.exists():
        return
    try:
        legacy.rename(db_path)
    except (FileNotFoundError, OSError):
        return
    for suffix in ("-shm", "-wal"):
        src = legacy.with_name(legacy.name + suffix)
        dst = db_path.with_name(db_path.name + suffix)
        try:
            if src.exists():
                src.rename(dst)
        except (FileNotFoundError, OSError):
            continue


def _migrate_legacy_schema(db_path: Path) -> None:
    """Rename briefing_runs→runs and briefing_markdown→markdown, in place.

    ALTER TABLE rename is not guarded by the sqlite_master snapshot under
    concurrent startup, so we catch OperationalError and treat "already
    migrated" as a no-op.
    """
    if not db_path.exists():
        return
    with sqlite3.connect(db_path) as conn:
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "briefing_runs" in tables and "runs" not in tables:
            try:
                conn.execute("ALTER TABLE briefing_runs RENAME TO runs")
            except sqlite3.OperationalError:
                pass
        cols = {
            r[1] for r in conn.execute("PRAGMA table_info(runs)")
        }
        if cols and "briefing_markdown" in cols and "markdown" not in cols:
            try:
                conn.execute(
                    "ALTER TABLE runs RENAME COLUMN briefing_markdown TO markdown"
                )
            except sqlite3.OperationalError:
                pass
        conn.commit()


def init_db(db_path: Path) -> None:
    """Create tables and set PRAGMAs. Idempotent; migrates legacy schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_file(db_path)
    _migrate_legacy_schema(db_path)
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(db_path: Path, write: bool = False) -> Iterator[Session]:
    """Open a Session; writes use BEGIN IMMEDIATE to avoid WAL deadlocks."""
    if _SessionFactory is None:
        get_engine(db_path)
    assert _SessionFactory is not None
    session = _SessionFactory()
    try:
        if write:
            session.execute(_BEGIN_IMMEDIATE_STMT)
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


from sqlalchemy import text  # noqa: E402

_BEGIN_IMMEDIATE_STMT = text("BEGIN IMMEDIATE")
