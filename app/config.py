"""Runtime configuration, read from environment variables.

The API ships in three variants so each change can be measured on its own:

    baseline   GET /events returns every matching row (no default limit),
               no secondary indexes. This is the deliberately naive version.
    paginated  GET /events applies a default limit of 50 (max 500).
               Still no secondary indexes.
    optimized  Pagination plus indexes on (lock_id, timestamp), (user_id) and
               (timestamp).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

VARIANTS = {
    "baseline": {"paginate": False, "indexes": False},
    "paginated": {"paginate": True, "indexes": False},
    "optimized": {"paginate": True, "indexes": True},
}


@dataclass(frozen=True)
class Settings:
    variant: str = "baseline"
    db_path: str = "data/events.db"
    default_limit: int = 50
    max_limit: int = 500
    slow_request_ms: float = 200.0
    slow_query_ms: float = 50.0
    log_file: str | None = None

    @property
    def paginate(self) -> bool:
        return VARIANTS[self.variant]["paginate"]

    @property
    def indexes(self) -> bool:
        return VARIANTS[self.variant]["indexes"]

    @classmethod
    def from_env(cls) -> "Settings":
        variant = os.getenv("APP_VARIANT", "baseline")
        if variant not in VARIANTS:
            raise ValueError(f"APP_VARIANT must be one of {sorted(VARIANTS)}, got {variant!r}")
        return cls(
            variant=variant,
            db_path=os.getenv("DB_PATH", "data/events.db"),
            default_limit=int(os.getenv("DEFAULT_LIMIT", "50")),
            max_limit=int(os.getenv("MAX_LIMIT", "500")),
            slow_request_ms=float(os.getenv("SLOW_REQUEST_MS", "200")),
            slow_query_ms=float(os.getenv("SLOW_QUERY_MS", "50")),
            log_file=os.getenv("LOG_FILE") or None,
        )
