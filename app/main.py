"""Access-event management API.

Run with:
    APP_VARIANT=baseline uvicorn app.main:app --port 8000
Interactive docs are served at /docs.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import make_engine, make_session_factory
from app.models import AccessEvent
from app.schemas import EventCreate, EventOut, EventType, Health

log = logging.getLogger("app.requests")


def _configure_logging(settings: Settings) -> None:
    root = logging.getLogger("app")
    root.setLevel(logging.INFO)
    if root.handlers:
        return
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handler = logging.FileHandler(settings.log_file) if settings.log_file else logging.StreamHandler()
    handler.setFormatter(fmt)
    root.addHandler(handler)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    _configure_logging(settings)

    engine = make_engine(settings)
    session_factory = make_session_factory(engine)

    app = FastAPI(
        title="Access Events API",
        version="1.0.0",
        description="Fictional access-event service used as a load-testing target. "
        f"Running variant: **{settings.variant}**.",
    )
    app.state.settings = settings
    app.state.engine = engine

    def get_db() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    @app.middleware("http")
    async def log_slow_requests(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Response-Time-ms"] = f"{elapsed_ms:.1f}"
        if elapsed_ms >= settings.slow_request_ms:
            log.warning(
                "slow_request ms=%.1f method=%s path=%s query=%s status=%s bytes=%s",
                elapsed_ms, request.method, request.url.path, request.url.query,
                response.status_code, response.headers.get("content-length", "?"),
            )
        return response

    @app.get("/health", response_model=Health, tags=["ops"])
    def health() -> Health:
        return Health(status="ok", variant=settings.variant)

    @app.get("/events", response_model=list[EventOut], tags=["events"])
    def list_events(
        lock_id: str | None = Query(None, pattern=r"^LOCK-\d{4}$"),
        user_id: str | None = Query(None, pattern=r"^USER-\d{5}$"),
        event_type: EventType | None = None,
        start: datetime | None = Query(None, alias="from"),
        end: datetime | None = Query(None, alias="to"),
        limit: int | None = Query(None, ge=1),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db),
    ):
        """List events, newest first, with optional filters.

        In the baseline variant an omitted `limit` returns every matching row.
        Paginated variants apply a default limit and cap it at `max_limit`.
        """
        stmt = select(AccessEvent)
        if lock_id:
            stmt = stmt.where(AccessEvent.lock_id == lock_id)
        if user_id:
            stmt = stmt.where(AccessEvent.user_id == user_id)
        if event_type:
            stmt = stmt.where(AccessEvent.event_type == event_type)
        if start:
            stmt = stmt.where(AccessEvent.timestamp >= start)
        if end:
            stmt = stmt.where(AccessEvent.timestamp <= end)
        stmt = stmt.order_by(AccessEvent.timestamp.desc(), AccessEvent.id.desc())

        if settings.paginate:
            limit = min(limit or settings.default_limit, settings.max_limit)
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset:
            stmt = stmt.offset(offset)
        return db.scalars(stmt).all()

    @app.get("/events/{event_id}", response_model=EventOut, tags=["events"])
    def get_event(event_id: int, db: Session = Depends(get_db)):
        event = db.get(AccessEvent, event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        return event

    @app.post("/events", response_model=EventOut, status_code=status.HTTP_201_CREATED, tags=["events"])
    def create_event(payload: EventCreate, db: Session = Depends(get_db)):
        event = AccessEvent(
            lock_id=payload.lock_id,
            user_id=payload.user_id,
            event_type=payload.event_type,
            timestamp=(payload.timestamp or datetime.now()).replace(tzinfo=None),
        )
        db.add(event)
        db.commit()
        return event

    return app


app = create_app()
