"""Run the load-test scenarios against one API variant and save everything.

    python scripts/run_suite.py --variant baseline                 # full suite (~45 min)
    python scripts/run_suite.py --variant optimized --repeat 2
    python scripts/run_suite.py --variant baseline --profile quick # ~6 min check
    python scripts/run_suite.py --variant optimized --profile smoke  # 30 s, used in CI
    python scripts/run_suite.py --variant baseline --scenarios load_50 stress

For every scenario the runner:
  1. reseeds the database, so each scenario starts from identical data,
  2. starts the API in a fresh uvicorn process (single worker),
  3. starts Locust headless, plus a psutil monitor on both processes,
  4. stops everything and records metadata and the threshold verdict.

Output: results/<variant>/run-<k>/<scenario>/
    locust_stats.csv, locust_stats_history.csv, locust_failures.csv,
    locust_exceptions.csv, report.html, monitor.csv, app.log, locust.log, meta.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

# name: (users, duration in seconds, uses step-stress shape)
PROFILES = {
    "full": {
        "baseline": (5, 120, False),
        "load_10": (10, 240, False),
        "load_25": (25, 240, False),
        "load_50": (50, 240, False),
        "stress": (100, 300, True),
        "endurance": (20, 1500, False),
    },
    "quick": {
        "baseline": (5, 30, False),
        "load_10": (10, 30, False),
        "load_25": (25, 30, False),
        "load_50": (50, 30, False),
        "stress": (100, 60, True),
        "endurance": (20, 120, False),
    },
    "smoke": {
        "smoke": (10, 30, False),
    },
}


def wait_healthy(url: str, timeout: float = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return
        except OSError:
            time.sleep(0.3)
    raise RuntimeError(f"API did not become healthy at {url}")


def stop(proc: subprocess.Popen, timeout: float = 15) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def machine_info() -> dict:
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_cpus": psutil.cpu_count(),
        "physical_cpus": psutil.cpu_count(logical=False),
        "total_ram_gb": round(psutil.virtual_memory().total / 2**30, 1),
        "python": platform.python_version(),
    }


def run_scenario(name: str, users: int, duration: int, shaped: bool, args, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    db_path = ROOT / "data" / f"{args.variant}.db"
    base_env = {**os.environ, "APP_VARIANT": args.variant, "DB_PATH": str(db_path),
                "SEED_EVENTS": str(args.events), "PYTHONPATH": str(ROOT)}

    subprocess.run([PY, "-m", "app.seed", "--variant", args.variant, "--db", str(db_path),
                    "--events", str(args.events)], cwd=ROOT, env=base_env, check=True)

    server_env = {**base_env, "LOG_FILE": str(out / "app.log")}
    server = subprocess.Popen(
        [PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.port),
         "--log-level", "warning", "--no-access-log"],
        cwd=ROOT, env=server_env)
    host = f"http://127.0.0.1:{args.port}"
    monitor = None
    try:
        wait_healthy(f"{host}/health")

        locust_files = "loadtest/locustfile.py" + (",loadtest/stress_shape.py" if shaped else "")
        cmd = [PY, "-m", "locust", "-f", locust_files, "--headless", "--host", host,
               "--csv", str(out / "locust"), "--csv-full-history", "--html", str(out / "report.html"),
               "--logfile", str(out / "locust.log"), "--only-summary", "--stop-timeout", "5"]
        if shaped:
            locust_env = {**base_env, "STRESS_TOTAL_S": str(duration)}
        else:
            cmd += ["-u", str(users), "-r", str(max(1, users // 10)), "-t", f"{duration}s"]
            locust_env = base_env
        if args.locust_processes > 1:
            cmd += ["--processes", str(args.locust_processes)]

        print(f"  -> {name}: {'50 to 100 step' if shaped else users} users, {duration}s", flush=True)
        started = datetime.now(timezone.utc)
        summary_txt = open(out / "locust_summary.txt", "w")
        locust = subprocess.Popen(cmd, cwd=ROOT, env=locust_env,
                                  stdout=summary_txt, stderr=subprocess.STDOUT)
        monitor = subprocess.Popen(
            [PY, str(ROOT / "scripts" / "monitor.py"), "--pid", f"server={server.pid}",
             "--pid", f"locust={locust.pid}", "--out", str(out / "monitor.csv")], cwd=ROOT)
        exit_code = locust.wait()
        summary_txt.close()
    finally:
        if monitor:
            stop(monitor)
        stop(server)

    meta = {
        "variant": args.variant, "scenario": name, "users": "50-100 step" if shaped else users,
        "duration_s": duration, "seed_events": args.events, "started_utc": started.isoformat(),
        "locust_exit_code": exit_code, "thresholds_passed": exit_code == 0,
        "p95_threshold_ms": float(os.getenv("P95_MS", "500")),
        "max_fail_ratio": float(os.getenv("MAX_FAIL_RATIO", "0.01")),
        "locust_processes": args.locust_processes, "machine": machine_info(),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"     thresholds {'PASS' if exit_code == 0 else 'FAIL'} (exit code {exit_code})", flush=True)
    return meta


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--variant", required=True, choices=["baseline", "paginated", "optimized"])
    p.add_argument("--profile", default="full", choices=sorted(PROFILES))
    p.add_argument("--scenarios", nargs="*", help="subset of scenario names from the profile")
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--events", type=int, default=int(os.getenv("SEED_EVENTS", "20000")))
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--locust-processes", type=int, default=1)
    p.add_argument("--results", default="results")
    p.add_argument("--clean", action="store_true", help="delete earlier results for this variant first")
    p.add_argument("--strict", action="store_true", help="exit non-zero if any scenario fails thresholds")
    args = p.parse_args()

    scenarios = PROFILES[args.profile]
    if args.scenarios:
        unknown = set(args.scenarios) - set(scenarios)
        if unknown:
            p.error(f"unknown scenarios for profile {args.profile}: {sorted(unknown)}")
        scenarios = {k: v for k, v in scenarios.items() if k in args.scenarios}

    variant_dir = ROOT / args.results / args.variant
    if args.clean and variant_dir.exists():
        shutil.rmtree(variant_dir)

    failed = []
    for k in range(1, args.repeat + 1):
        print(f"[{args.variant}] run {k}/{args.repeat}, profile {args.profile}", flush=True)
        for name, (users, duration, shaped) in scenarios.items():
            meta = run_scenario(name, users, duration, shaped, args, variant_dir / f"run-{k}" / name)
            if not meta["thresholds_passed"]:
                failed.append(f"run-{k}/{name}")

    subprocess.run([PY, str(ROOT / "scripts" / "summarize.py"), str(variant_dir)], check=True)
    if failed:
        print(f"Scenarios that failed thresholds: {', '.join(failed)}")
    if args.strict and failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
