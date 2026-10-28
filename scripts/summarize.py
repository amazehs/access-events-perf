"""Summarise one variant's results into summary.csv and summary.md.

    python scripts/summarize.py results/baseline

Reads every results/<variant>/run-<k>/<scenario>/ folder. With several runs the
Markdown table shows the median across runs and the p95 range (min to max), so
run-to-run variation is visible rather than hidden.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path

SCENARIO_ORDER = ["smoke", "baseline", "load_10", "load_25", "load_50", "stress", "endurance"]
KEY_ENDPOINTS = ["/events (recent)", "/events?lock_id", "/events?user_id", "/events/{id}", "POST /events"]


def _num(v: str) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def read_stats(path: Path) -> dict[str, dict]:
    with open(path, newline="") as f:
        return {row["Name"]: row for row in csv.DictReader(f)}


def read_monitor(path: Path) -> dict:
    out: dict = {}
    if not path.exists():
        return out
    rows = list(csv.DictReader(open(path, newline="")))
    for proc in ("server", "locust"):
        cpu = [float(r["cpu_percent"]) for r in rows if r["process"] == proc]
        rss = [float(r["rss_mb"]) for r in rows if r["process"] == proc]
        if cpu:
            out[f"{proc}_cpu_mean"] = round(statistics.mean(cpu), 1)
            out[f"{proc}_cpu_max"] = round(max(cpu), 1)
            out[f"{proc}_rss_start_mb"] = rss[0]
            out[f"{proc}_rss_end_mb"] = rss[-1]
            out[f"{proc}_rss_max_mb"] = max(rss)
    sys_cpu = [float(r["system_cpu_percent"]) for r in rows]
    if sys_cpu:
        out["system_cpu_max"] = round(max(sys_cpu), 1)
    return out


def count_slow(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    text = path.read_text().splitlines()
    return (sum("slow_request" in line for line in text), sum("slow_query" in line for line in text))


def summarize_scenario(d: Path) -> dict:
    stats = read_stats(d / "locust_stats.csv")
    agg = stats["Aggregated"]
    meta = json.loads((d / "meta.json").read_text()) if (d / "meta.json").exists() else {}
    reqs = int(agg["Request Count"])
    fails = int(agg["Failure Count"])
    slow_req, slow_q = count_slow(d / "app.log")
    row = {
        "run": d.parent.name,
        "scenario": d.name,
        "users": meta.get("users", ""),
        "duration_s": meta.get("duration_s", ""),
        "requests": reqs,
        "failures": fails,
        "fail_ratio_pct": round(100 * fails / reqs, 2) if reqs else None,
        "rps": round(float(agg["Requests/s"]), 2),
        "median_ms": _num(agg["50%"]),
        "p95_ms": _num(agg["95%"]),
        "p99_ms": _num(agg["99%"]),
        "max_ms": round(float(agg["Max Response Time"])),
        "thresholds_passed": meta.get("thresholds_passed", ""),
        "slow_requests_logged": slow_req,
        "slow_queries_logged": slow_q,
    }
    for ep in KEY_ENDPOINTS:
        if ep in stats:
            row[f"p95_ms[{ep}]"] = _num(stats[ep]["95%"])
    row.update(read_monitor(d / "monitor.csv"))
    return row


def fmt(v) -> str:
    if v is None or v == "":
        return "n/a"
    if isinstance(v, float):
        return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.1f}"
    return str(v)


def median_of(rows: list[dict], key: str):
    vals = [r[key] for r in rows if isinstance(r.get(key), (int, float)) and not isinstance(r.get(key), bool)]
    return statistics.median(vals) if vals else None


def main() -> None:
    variant_dir = Path(sys.argv[1])
    scenario_dirs = sorted(p.parent for p in variant_dir.glob("run-*/*/locust_stats.csv"))
    if not scenario_dirs:
        sys.exit(f"No results found under {variant_dir}")
    rows = [summarize_scenario(d) for d in scenario_dirs]
    order = {s: i for i, s in enumerate(SCENARIO_ORDER)}
    rows.sort(key=lambda r: (order.get(r["scenario"], 99), r["run"]))

    fields = list(dict.fromkeys(k for r in rows for k in r))
    with open(variant_dir / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    scenarios = list(dict.fromkeys(r["scenario"] for r in rows))
    n_runs = len({r["run"] for r in rows})
    lines = [
        f"# Results: {variant_dir.name}",
        "",
        f"Runs: {n_runs}. Values are medians across runs; the p95 range shows min to max across runs.",
        "Response times in ms. CPU in percent of one core (can exceed 100). Memory is the API process RSS.",
        "",
        "| Scenario | Users | Requests/s | Median | p95 | p95 range | p99 | Failures % | Server CPU mean/max | Server RSS start/end MB | Thresholds |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in scenarios:
        rs = [r for r in rows if r["scenario"] == s]
        p95s = [r["p95_ms"] for r in rs if r["p95_ms"] is not None]
        rng = f"{min(p95s):,.0f} to {max(p95s):,.0f}" if len(p95s) > 1 else "single run"
        passed = sum(r["thresholds_passed"] is True for r in rs)
        lines.append(
            f"| {s} | {rs[0]['users']} | {fmt(median_of(rs, 'rps'))} | {fmt(median_of(rs, 'median_ms'))} "
            f"| {fmt(median_of(rs, 'p95_ms'))} | {rng} | {fmt(median_of(rs, 'p99_ms'))} "
            f"| {fmt(median_of(rs, 'fail_ratio_pct'))} "
            f"| {fmt(median_of(rs, 'server_cpu_mean'))} / {fmt(median_of(rs, 'server_cpu_max'))} "
            f"| {fmt(median_of(rs, 'server_rss_start_mb'))} / {fmt(median_of(rs, 'server_rss_end_mb'))} "
            f"| {passed}/{len(rs)} pass |"
        )
    lines += ["", "## p95 by endpoint (ms, median across runs)", "",
              "| Scenario | " + " | ".join(f"`{e}`" for e in KEY_ENDPOINTS) + " |",
              "|---|" + "---|" * len(KEY_ENDPOINTS)]
    for s in scenarios:
        rs = [r for r in rows if r["scenario"] == s]
        lines.append(f"| {s} | " + " | ".join(fmt(median_of(rs, f"p95_ms[{e}]")) for e in KEY_ENDPOINTS) + " |")
    lines += ["", "## Load generator check", "",
              "If Locust's own CPU is near 100 (one core), the load generator may be limiting the test.", "",
              "| Scenario | Locust CPU max | System CPU max |", "|---|---|---|"]
    for s in scenarios:
        rs = [r for r in rows if r["scenario"] == s]
        lines.append(f"| {s} | {fmt(median_of(rs, 'locust_cpu_max'))} | {fmt(median_of(rs, 'system_cpu_max'))} |")

    (variant_dir / "summary.md").write_text("\n".join(lines) + "\n")
    print(f"Wrote {variant_dir / 'summary.csv'} and {variant_dir / 'summary.md'}")


if __name__ == "__main__":
    main()
