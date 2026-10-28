# Access Events API: Performance Testing with FastAPI and Locust

![CI](https://github.com/YOUR-USERNAME/access-events-perf/actions/workflows/ci.yml/badge.svg)

A small REST API for a fictional access-control system (locks, users, unlock and
denied events), load-tested with Locust to find a performance bottleneck, fix it,
and measure the effect of the fix.

The API ships in three variants so each change is measured in isolation:

| Variant | `GET /events` without `limit` | Secondary indexes |
|---|---|---|
| `baseline` | returns every matching row (the planted flaw) | none |
| `paginated` | default 50 rows, capped at 500 | none |
| `optimized` | default 50 rows, capped at 500 | `(lock_id, timestamp)`, `(user_id)`, `(timestamp)` |

The baseline flaw was introduced on purpose, to give the investigation a real
bottleneck to find. Everything after that point (the measurements, the root
cause analysis and the before/after comparison) comes from the test runs.

Results and analysis: see [REPORT.md](REPORT.md).

## What the project shows

- A REST API with validation (Pydantic), filtering, pagination and generated OpenAPI docs (`/docs`).
- Locust user behaviour with a weighted, realistic request mix and full response validation,
  not just status codes, including negative paths (404, 422).
- Baseline, load, stress (step shape) and endurance scenarios, run headless with CSV and HTML output.
- Acceptance thresholds (p95 and failure ratio) that set Locust's exit code, used as a CI gate.
- CPU and memory monitoring of both the API and the load generator, slow-request and slow-query logs,
  and SQLite query plans as root-cause evidence.
- Reproducible runs: deterministic seed data, database reset before every scenario, pinned
  dependencies, repeated runs reported as median with range.
- Functional tests (pytest) for every variant, separate from the performance tests.

## Quick start

Requires Python 3.11 or newer. On macOS or Linux:

```bash
git clone https://github.com/YOUR-USERNAME/access-events-perf.git
cd access-events-perf
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

pytest -q                       # functional tests, all three variants
make serve VARIANT=baseline     # API on http://127.0.0.1:8000, docs at /docs
```

Run a load test in a second terminal while the server is up, using Locust's web UI:

```bash
locust -f loadtest/locustfile.py --host http://127.0.0.1:8000   # open http://localhost:8089
```

## Running the test suite

The runner handles everything for one variant: reseeds the database, starts the API,
runs Locust headless, monitors CPU and memory, stops everything and saves the results.

```bash
python scripts/run_suite.py --variant baseline --profile quick    # every scenario, shortened (~6 min)
python scripts/run_suite.py --variant baseline                    # full suite (~45 min)
python scripts/run_suite.py --variant optimized --repeat 2        # full suite twice
python scripts/compare.py results/baseline results/paginated results/optimized
```

`make suite-all` runs the full suite twice for every variant and then draws the
comparison charts. It takes about four and a half hours, so plug in the laptop and
close other heavy applications.

### Scenarios (full profile)

| Scenario | Users | Duration | Purpose |
|---|---|---|---|
| `baseline` | 5 | 2 min | reference latency at light load |
| `load_10`, `load_25`, `load_50` | 10, 25, 50 | 4 min each | behaviour as load increases |
| `stress` | 50 to 100, +10 per step | 5 min | find the saturation point |
| `endurance` | 20 | 25 min | degradation over time (memory, growing data) |

Each simulated user targets about one request per second (`constant_throughput(1)`),
so users approximate offered load in requests per second. When achieved throughput
falls below the user count, the server is saturated.

### Request mix

| Weight | Request | Notes |
|---|---|---|
| 6 | `GET /events?lock_id=...&limit=20` | lock history; checks filter and limit |
| 5 | `GET /events/{id}` | checks the returned ID |
| 3 | `POST /events` | checks the created event matches the request |
| 2 | `GET /events` | recent events feed; no limit sent (the planted bottleneck) |
| 2 | `GET /events?user_id=...` | user activity; checks the filter |
| 1 | `GET /events/999999999`, invalid `POST` | must return 404 and 422 |
| 1 | `GET /health` | |

### Acceptance thresholds

A run passes when the aggregated p95 is at most `P95_MS` (default 500 ms) and the
failure ratio is at most `MAX_FAIL_RATIO` (default 1%). Override them as
environment variables, for example `P95_MS=300 python scripts/run_suite.py ...`.
The stress scenario is expected to fail its thresholds at some point: finding
where it fails is its purpose.

### Output

```
results/<variant>/
  summary.md, summary.csv              medians across runs
  run-<k>/<scenario>/
    report.html                        Locust's interactive report
    locust_stats.csv                   per-endpoint totals and percentiles
    locust_stats_history.csv           time series (every few seconds)
    locust_failures.csv
    monitor.csv                        CPU and memory of the API and Locust, once per second
    app.log                            slow requests (>200 ms) and slow SQL queries (>50 ms)
    meta.json                          configuration, threshold verdict, machine details
results/comparison/
  comparison.md and PNG charts
```

`python scripts/explain_queries.py data/baseline.db` prints the SQLite query plans
and timings for the main queries (run `make explain` to seed both databases first).

## Methodology notes and limitations

- **Same machine.** Locust and the API run on the same laptop and compete for CPU.
  `monitor.csv` records Locust's own CPU so it is visible when the load generator,
  not the API, is the limit. For heavier tests, run Locust with `--locust-processes 4`
  or on a second machine.
- **Single worker.** The API runs one uvicorn worker in every variant, so the
  comparison isolates the code change. More workers would raise throughput for all
  variants and is a separate experiment.
- **SQLite.** Chosen for zero setup. It serialises writes, which matters at much
  higher write rates than this test produces. Results do not transfer directly to a
  client-server database.
- **Synthetic data.** 20,000 events across 500 locks and 2,000 users, generated with a
  fixed seed (`SEED_EVENTS` changes the size). Real access data would be skewed
  towards busy doors and working hours.
- **Coordinated omission.** Locust users wait for each response before sending the
  next, so under saturation the offered load drops and latency percentiles understate
  what an open-loop client would see. Throughput falling below the user count is the
  signal to watch.

## Project structure

```
app/                FastAPI service: config, models, schemas, database, seed data
loadtest/           Locust user behaviour and the stress step shape
scripts/            suite runner, process monitor, summaries, charts, query plans
tests/              functional tests (pytest)
.github/workflows/  CI: functional tests, then a threshold-gated smoke load test
results/            saved results from local runs
REPORT.md           performance report
```

## Licence

MIT
