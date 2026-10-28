"""Database setup: SQLite through SQLAlchemy, with slow-query logging."""

from __future__ import annotations

import logging
import time

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.models import Base

log = logging.getLogger("app.db")

# Secondary indexes, created only by variants that enable them. Plain DDL keeps them
# out of the ORM metadata, so create_all() never adds them to the baseline schema.
INDEXES = [
    "CREATE INDEX ix_events_lock_ts ON access_events (lock_id, timestamp)",
    "CREATE INDEX ix_events_user ON access_events (user_id)",
    "CREATE INDEX ix_events_ts ON access_events (timestamp)",
]


def make_engine(settings: Settings) -> Engine:
    engine = create_engine(
        f"sqlite:///{settings.db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_size=20,
        max_overflow=20,
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")      # readers do not block the writer
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    @event.listens_for(engine, "before_cursor_execute")
    def _start_timer(conn, _cursor, _stmt, _params, _ctx, _many):
        conn.info.setdefault("query_start", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _log_slow(conn, _cursor, statement, params, _ctx, executemany):
        elapsed_ms = (time.perf_counter() - conn.info["query_start"].pop()) * 1000
        if elapsed_ms >= settings.slow_query_ms and not executemany:  # skip bulk seeding
            log.warning("slow_query ms=%.1f sql=%s params=%s",
                        elapsed_ms, " ".join(statement.split()), repr(params)[:200])

    return engine


def init_schema(engine: Engine, with_indexes: bool) -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    if with_indexes:
        with engine.begin() as conn:
            for ddl in INDEXES:
                conn.execute(text(ddl))


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
