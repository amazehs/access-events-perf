"""Show SQLite's query plan for the API's main queries, for root-cause evidence.

    python scripts/explain_queries.py data/baseline.db
    python scripts/explain_queries.py data/optimized.db

"SCAN access_events" means a full table scan; "SEARCH ... USING INDEX" means an
index lookup; "USE TEMP B-TREE FOR ORDER BY" means a sort of the matching rows.
Each query is also timed (median of 20 executions, server-side, no HTTP).
"""

from __future__ import annotations

import sqlite3
import statistics
import sys
import time

QUERIES = {
    "recent events, no limit (baseline /events)":
        ("SELECT * FROM access_events ORDER BY timestamp DESC, id DESC", ()),
    "recent events, limit 50 (paginated /events)":
        ("SELECT * FROM access_events ORDER BY timestamp DESC, id DESC LIMIT 50", ()),
    "lock history, limit 20":
        ("SELECT * FROM access_events WHERE lock_id = ? ORDER BY timestamp DESC, id DESC LIMIT 20", ("LOCK-0042",)),
    "user activity":
        ("SELECT * FROM access_events WHERE user_id = ? ORDER BY timestamp DESC, id DESC", ("USER-00042",)),
}


def main() -> None:
    db = sqlite3.connect(sys.argv[1] if len(sys.argv) > 1 else "data/baseline.db")
    n = db.execute("SELECT count(*) FROM access_events").fetchone()[0]
    print(f"{sys.argv[1] if len(sys.argv) > 1 else 'data/baseline.db'}: {n} rows\n")
    for name, (sql, params) in QUERIES.items():
        plan = [row[-1] for row in db.execute("EXPLAIN QUERY PLAN " + sql, params)]
        times = []
        for _ in range(20):
            t = time.perf_counter()
            rows = db.execute(sql, params).fetchall()
            times.append((time.perf_counter() - t) * 1000)
        print(f"{name}\n  plan: {' | '.join(plan)}\n  rows: {len(rows)}, median {statistics.median(times):.2f} ms\n")


if __name__ == "__main__":
    main()
