# Performance Report: Access Events API

<!--
HOW TO USE THIS TEMPLATE
1. Run the full suite on your own machine for all three variants:  make suite-all
2. Fill every [FILL] marker from results/<variant>/summary.md, results/comparison/comparison.md,
   the app.log files and scripts/explain_queries.py.
3. Write only what your numbers show. If a result surprises you, report it as it is.
4. Delete these comment blocks before publishing.
-->

**Author:** Haider Israr
**Date of test runs:** [FILL]
**Repository commit:** [FILL: output of `git rev-parse --short HEAD`]

## 1. Summary

[FILL: three or four sentences. What was tested, what broke and at what load, the root cause,
the fix, and the measured effect. Example shape: "Under N concurrent users the baseline API's
p95 rose from X ms to Y ms and throughput levelled off at Z requests/s. The cause was ... .
Adding pagination reduced p95 at 50 users from X to Y ms ... ."]

## 2. System under test

A FastAPI service for a fictional access-control system, backed by SQLite through SQLAlchemy,
running as a single uvicorn worker. Endpoints: `GET /health`, `GET /events` (filters: lock,
user, type, time range; `limit`/`offset`), `GET /events/{id}`, `POST /events`.
Seed data: 20,000 events, 500 locks, 2,000 users, fixed random seed.

| Variant | Change |
|---|---|
| baseline | `GET /events` with no `limit` returns every row; no secondary indexes |
| paginated | default limit 50, maximum 500 |
| optimized | pagination plus indexes on `(lock_id, timestamp)`, `(user_id)`, `(timestamp)` |

## 3. Test environment

| Item | Value |
|---|---|
| Machine | [FILL: from meta.json, e.g. MacBook Air M4] |
| CPU cores (logical / physical) | [FILL] |
| RAM | [FILL] |
| OS | [FILL] |
| Python | [FILL] |
| Locust / FastAPI / uvicorn | 2.47.0 / 0.162.0 / 0.54.0 |

Locust and the API ran on the same machine. Locust's own CPU was monitored throughout;
its maximum was [FILL] % of one core, so [FILL: the load generator was / was not a limiting factor].

## 4. Test design

Each simulated user targets one request per second with a weighted mix: lock history lookups (6),
single-event reads (5), event creation (3), the recent-events feed without a limit (2),
user activity lookups (2), negative checks expecting 404 and 422 (1) and health checks (1).
Every response is validated for content as well as status code.

| Scenario | Users | Duration |
|---|---|---|
| Baseline | 5 | 2 min |
| Load | 10, 25, 50 | 4 min each |
| Stress | 50 to 100, +10 per step | 5 min |
| Endurance | 20 | 25 min |

The database is reseeded before every scenario. Each scenario was run [FILL: 2] times per
variant; tables show the median, with the p95 range across runs where relevant.

Acceptance thresholds: p95 at most 500 ms and failure ratio at most 1%.

## 5. Baseline results

[FILL: paste the main table from results/baseline/summary.md]

Observations:

- [FILL: at which load did p95 first exceed the threshold?]
- [FILL: did achieved requests/s keep up with the user count? Where did it stop?]
- [FILL: server CPU at that point. Close to 100 % means one core was saturated.]
- [FILL: any failures, and what kind (check locust_failures.csv)?]

![p95 by scenario](results/comparison/p95_by_scenario.png)

## 6. Investigation

<!--
Work from symptom to cause and show the evidence for each step. Useful sources:
 - "p95 by endpoint" in results/baseline/summary.md: which endpoint is slow, and are fast
   endpoints also slow under load (a sign of queueing behind something else)?
 - app.log: slow_request lines show path, query and response size in bytes.
 - Average Content Size column in locust_stats.csv: how large were responses?
 - monitor.csv: server CPU near 100 means a single-core bottleneck.
 - python scripts/explain_queries.py data/baseline.db: query plans and DB-only timings.
   Compare the DB time with the HTTP response time to see where the time goes.
-->

**Symptom.** [FILL]

**Hypotheses considered.** [FILL: e.g. slow SQL from missing indexes; large response
serialisation; write contention in SQLite; load generator limits.]

**Evidence.**

- [FILL: per-endpoint p95 at 50 users for `/events (recent)` vs `/events/{id}`]
- [FILL: response size of the recent-events feed, from app.log or locust_stats.csv]
- [FILL: query plan and DB-only time vs total response time]
- [FILL: server CPU]

**Root cause.** [FILL]

## 7. Fix and verification

[FILL: describe the change and paste the relevant rows of results/comparison/comparison.md]

| Scenario | Metric | baseline | paginated | optimized |
|---|---|---|---|---|
| load_50 | p95 ms | [FILL] | [FILL] | [FILL] |
| load_50 | requests/s | [FILL] | [FILL] | [FILL] |
| stress | p95 ms | [FILL] | [FILL] | [FILL] |

[FILL: what did pagination alone change, and what did the indexes add on top? If the
indexes made little difference at this data size, say so and explain why.]

![Throughput by scenario](results/comparison/throughput_by_scenario.png)
![Stress p95](results/comparison/stress_p95.png)

## 8. Endurance

[FILL: did p95 or memory drift over 25 minutes? The table grows by roughly 3 inserts per
second during this run, so the baseline feed gets larger over time.]

![Endurance p95](results/comparison/endurance_p95.png)
![Endurance memory](results/comparison/endurance_memory.png)

## 9. Recommendations

[FILL: evidence-based, ordered by impact. Possible directions, keep only those your data supports:
always paginate list endpoints and cap the page size; keyset pagination for deep pages;
indexes matched to the filter and sort columns once data grows; more uvicorn workers for
CPU-bound load; keep the threshold-gated smoke test in CI to catch regressions.]

## 10. Limitations

Same-machine load generation, single worker, SQLite, synthetic and uniformly distributed data,
closed-loop users (coordinated omission). See the README for details.

## 11. Reproduce

```bash
pip install -r requirements.txt
make suite-all     # or: python scripts/run_suite.py --variant <name> --repeat 2
make compare
```
