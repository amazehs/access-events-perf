"""Create a fresh database with deterministic synthetic access events.

    python -m app.seed --variant baseline --events 20000

The same seed and anchor date always produce the same rows, so every test run
starts from an identical dataset.
"""

from __future__ import annotations

import argparse
import os
import random
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import insert

from app.config import VARIANTS, Settings
from app.db import init_schema, make_engine
from app.models import AccessEvent

N_LOCKS = 500
N_USERS = 2000
ANCHOR = datetime(2026, 1, 1)   # fixed so the data is reproducible
SPAN_DAYS = 90
EVENT_WEIGHTS = {"unlock": 0.70, "lock": 0.22, "denied": 0.08}


def generate(n_events: int, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    types, weights = zip(*EVENT_WEIGHTS.items())
    span_s = SPAN_DAYS * 86400
    return [
        {
            "lock_id": f"LOCK-{rng.randint(1, N_LOCKS):04d}",
            "user_id": f"USER-{rng.randint(1, N_USERS):05d}",
            "event_type": rng.choices(types, weights)[0],
            "timestamp": ANCHOR - timedelta(seconds=rng.randint(0, span_s)),
        }
        for _ in range(n_events)
    ]


def seed(settings: Settings, n_events: int, seed_value: int = 42) -> None:
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(settings.db_path + suffix)
        except FileNotFoundError:
            pass
    engine = make_engine(settings)
    init_schema(engine, with_indexes=settings.indexes)
    with engine.begin() as conn:
        conn.execute(insert(AccessEvent), generate(n_events, seed_value))
    engine.dispose()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--variant", choices=sorted(VARIANTS), default=os.getenv("APP_VARIANT", "baseline"))
    p.add_argument("--db", default=os.getenv("DB_PATH", "data/events.db"))
    p.add_argument("--events", type=int, default=int(os.getenv("SEED_EVENTS", "20000")))
    p.add_argument("--seed", type=int, default=42)
    a = p.parse_args()
    settings = Settings(variant=a.variant, db_path=a.db)
    seed(settings, a.events, a.seed)
    print(f"Seeded {a.events} events into {a.db} (variant={a.variant}, indexes={settings.indexes})")


if __name__ == "__main__":
    main()
