"""SQLAlchemy 2.0 schema — sync engine, WAL mode, single-writer.

Three tables:
  runs             — one row per pipeline attempt (success or failure)
  watermarks       — key/value; holds `last_successful_run_at` (UTC ISO)
  config_snapshots — versioned prompt/rules edits for rollback

Uses BEGIN IMMEDIATE for writes to keep the single-writer invariant under
systemd-launched runs + the web process.
"""
from __future__ import annotations

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


def init_db(db_path: Path) -> None:
    """Create tables and set PRAGMAs. Idempotent.

    Also tightens filesystem perms: the parent dir is chmod 0700 and the
    DB file (plus any WAL/SHM siblings) chmod 0600, so the local database
    — which holds run history and generated markdown — is not readable by
    other users on shared systems. Best-effort on filesystems that don't
    support POSIX modes.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)

    try:
        db_path.parent.chmod(0o700)
    except OSError:
        pass
    for suffix in ("", "-shm", "-wal"):
        candidate = (
            db_path if not suffix else db_path.with_name(db_path.name + suffix)
        )
        if candidate.exists():
            try:
                candidate.chmod(0o600)
            except OSError:
                pass


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
