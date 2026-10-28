"""Locust user behaviour for the Access Events API.

Each simulated user targets about one request per second (constant_throughput),
so the number of users is a direct proxy for offered load. When the server slows
down, users cannot keep pace and measured throughput drops below the user count;
that gap is itself a signal of saturation.

Every response is validated, not just its status code. Pass/fail thresholds are
checked when the run ends and decide Locust's exit code, so the same file works
for exploratory runs and as a CI gate.

Environment variables:
    SEED_EVENTS     size of the seeded dataset (for picking existing IDs), default 20000
    P95_MS          95th percentile threshold in ms, default 500
    MAX_FAIL_RATIO  maximum failure ratio, default 0.01
    THROUGHPUT      target requests per second per user, default 1.0
"""

from __future__ import annotations

import logging
import os
import random

from locust import HttpUser, constant_throughput, events, task

SEED_EVENTS = int(os.getenv("SEED_EVENTS", "20000"))
P95_MS = float(os.getenv("P95_MS", "500"))
MAX_FAIL_RATIO = float(os.getenv("MAX_FAIL_RATIO", "0.01"))
THROUGHPUT = float(os.getenv("THROUGHPUT", "1.0"))

N_LOCKS = 500
N_USERS = 2000
EVENT_TYPES = ("unlock", "lock", "denied")


def rand_lock() -> str:
    return f"LOCK-{random.randint(1, N_LOCKS):04d}"


def rand_user() -> str:
    return f"USER-{random.randint(1, N_USERS):05d}"


class AccessEventsUser(HttpUser):
    """A client of the access-event service: mostly reads, some writes.

    Approximate request mix (task weights in brackets):
        lock history lookup        [6]  GET /events?lock_id=...&limit=20
        single event by ID         [5]  GET /events/{id}
        recent events feed         [2]  GET /events            (no limit: the planted bottleneck)
        user activity lookup       [2]  GET /events?user_id=...
        record a new event         [3]  POST /events
        negative checks            [1]  404 and 422 paths
        health                     [1]  GET /health
    """

    wait_time = constant_throughput(THROUGHPUT)

    def on_start(self) -> None:
        self.created_ids: list[int] = []

    @task(6)
    def lock_history(self) -> None:
        lock = rand_lock()
        with self.client.get(
            "/events", params={"lock_id": lock, "limit": 20},
            name="/events?lock_id", catch_response=True,
        ) as r:
            if r.status_code != 200:
                r.failure(f"status {r.status_code}")
                return
            body = r.json()
            if len(body) > 20:
                r.failure(f"limit ignored: {len(body)} rows")
            elif any(e["lock_id"] != lock for e in body):
                r.failure("filter returned events for another lock")

    @task(5)
    def event_by_id(self) -> None:
        pool = self.created_ids[-50:]
        event_id = random.choice(pool) if pool and random.random() < 0.2 else random.randint(1, SEED_EVENTS)
        with self.client.get(f"/events/{event_id}", name="/events/{id}", catch_response=True) as r:
            if r.status_code != 200:
                r.failure(f"status {r.status_code}")
            elif r.json().get("id") != event_id:
                r.failure("returned the wrong event")

    @task(2)
    def recent_events(self) -> None:
        with self.client.get("/events", name="/events (recent)", catch_response=True) as r:
            if r.status_code != 200:
                r.failure(f"status {r.status_code}")
            elif not isinstance(r.json(), list):
                r.failure("expected a list")

    @task(2)
    def user_activity(self) -> None:
        user = rand_user()
        with self.client.get("/events", params={"user_id": user}, name="/events?user_id", catch_response=True) as r:
            if r.status_code != 200:
                r.failure(f"status {r.status_code}")
            elif any(e["user_id"] != user for e in r.json()):
                r.failure("filter returned events for another user")

    @task(3)
    def create_event(self) -> None:
        payload = {"lock_id": rand_lock(), "user_id": rand_user(), "event_type": random.choice(EVENT_TYPES)}
        with self.client.post("/events", json=payload, name="POST /events", catch_response=True) as r:
            if r.status_code != 201:
                r.failure(f"status {r.status_code}")
                return
            body = r.json()
            if any(body.get(k) != v for k, v in payload.items()):
                r.failure("created event does not match the request")
            else:
                self.created_ids.append(body["id"])

    @task(1)
    def negative_paths(self) -> None:
        # A missing event must be a clean 404, and invalid input a 422.
        with self.client.get("/events/999999999", name="/events/{id} (404)", catch_response=True) as r:
            if r.status_code == 404:
                r.success()
            else:
                r.failure(f"expected 404, got {r.status_code}")
        bad = {"lock_id": "not-a-lock", "user_id": rand_user(), "event_type": "teleport"}
        with self.client.post("/events", json=bad, name="POST /events (422)", catch_response=True) as r:
            if r.status_code == 422:
                r.success()
            else:
                r.failure(f"expected 422, got {r.status_code}")

    @task(1)
    def health(self) -> None:
        with self.client.get("/health", name="/health", catch_response=True) as r:
            if r.status_code != 200 or r.json().get("status") != "ok":
                r.failure("unhealthy")


@events.quitting.add_listener
def check_thresholds(environment, **_kwargs) -> None:
    """Fail the run (non-zero exit code) when the acceptance thresholds are not met."""
    total = environment.stats.total
    if total.num_requests == 0:
        logging.error("THRESHOLD FAIL: no requests were made")
        environment.process_exit_code = 1
        return
    p95 = total.get_response_time_percentile(0.95)
    problems = []
    if total.fail_ratio > MAX_FAIL_RATIO:
        problems.append(f"failure ratio {total.fail_ratio:.2%} > {MAX_FAIL_RATIO:.2%}")
    if p95 > P95_MS:
        problems.append(f"p95 {p95:.0f} ms > {P95_MS:.0f} ms")
    if problems:
        logging.error("THRESHOLD FAIL: %s", "; ".join(problems))
        environment.process_exit_code = 1
    else:
        logging.info("THRESHOLD PASS: p95 %.0f ms, failure ratio %.2f%%", p95, total.fail_ratio * 100)
        environment.process_exit_code = 0
