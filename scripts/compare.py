"""Compare variants side by side and draw the plots used in the report.

    python scripts/compare.py results/baseline results/paginated results/optimized

Writes results/comparison/comparison.md and PNG charts:
    p95_by_scenario.png        p95 per scenario, one bar per variant
    throughput_by_scenario.png achieved requests/s per scenario
    endurance_p95.png          p95 over time during the endurance run
    endurance_memory.png       API process memory over time during the endurance run
    stress_p95.png             p95 over time as the stress test steps up users
Time-series charts use run-1 of each variant.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from summarize import SCENARIO_ORDER, median_of  # noqa: E402

COLORS = {"baseline": "#2a78d6", "paginated": "#eb6834", "optimized": "#1baf7a"}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"

plt.rcParams.update({
    "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb", "axes.edgecolor": GRID,
    "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10,
    "axes.titlesize": 12, "axes.titleweight": "bold", "legend.frameon": False,
})


def load_summary(variant_dir: Path) -> list[dict]:
    rows = []
    for r in csv.DictReader(open(variant_dir / "summary.csv", newline="")):
        rows.append({k: (float(v) if _isnum(v) else v) for k, v in r.items()})
    return rows


def _isnum(v: str) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def history(variant_dir: Path, scenario: str) -> tuple[list[float], list[float], list[float]]:
    path = variant_dir / "run-1" / scenario / "locust_stats_history.csv"
    if not path.exists():
        return [], [], []
    t, p95, users = [], [], []
    t0 = None
    for r in csv.DictReader(open(path, newline="")):
        if r["Name"] != "Aggregated" or r["95%"] in ("N/A", ""):
            continue
        ts = float(r["Timestamp"])
        t0 = t0 if t0 is not None else ts
        t.append((ts - t0) / 60)
        p95.append(float(r["95%"]))
        users.append(float(r["User Count"]))
    return t, p95, users


def memory(variant_dir: Path, scenario: str) -> tuple[list[float], list[float]]:
    path = variant_dir / "run-1" / scenario / "monitor.csv"
    if not path.exists():
        return [], []
    rows = [r for r in csv.DictReader(open(path, newline="")) if r["process"] == "server"]
    return [float(r["elapsed_s"]) / 60 for r in rows], [float(r["rss_mb"]) for r in rows]


def grouped_bars(data: dict[str, dict[str, float]], scenarios: list[str], ylabel: str, title: str, out: Path,
                 log: bool = False) -> None:
    variants = list(data)
    fig, ax = plt.subplots(figsize=(9, 4.2))
    width = 0.8 / len(variants)
    for i, v in enumerate(variants):
        xs = [j + (i - (len(variants) - 1) / 2) * width for j in range(len(scenarios))]
        ys = [data[v].get(s) or 0 for s in scenarios]
        ax.bar(xs, ys, width * 0.92, label=v, color=COLORS.get(v, MUTED))
    ax.set_xticks(range(len(scenarios)), scenarios)
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left")
    if log:
        ax.set_yscale("log")
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper left", ncols=len(variants))
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def lines(series: dict[str, tuple[list[float], list[float]]], xlabel: str, ylabel: str, title: str,
          out: Path, log: bool = False) -> None:
    fig, ax = plt.subplots(figsize=(9, 4.2))
    for v, (x, y) in series.items():
        if x:
            ax.plot(x, y, color=COLORS.get(v, MUTED), linewidth=2, label=v)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left")
    if log:
        ax.set_yscale("log")
    ax.legend(loc="upper left", ncols=len(series))
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def main() -> None:
    dirs = [Path(p) for p in sys.argv[1:]]
    if not dirs:
        sys.exit(__doc__)
    out = dirs[0].parent / "comparison"
    out.mkdir(parents=True, exist_ok=True)

    summaries = {d.name: load_summary(d) for d in dirs}
    present = {r["scenario"] for rows in summaries.values() for r in rows}
    scenarios = [s for s in SCENARIO_ORDER if s in present]

    def per_scenario(key: str) -> dict[str, dict[str, float]]:
        return {v: {s: median_of([r for r in rows if r["scenario"] == s], key) for s in scenarios}
                for v, rows in summaries.items()}

    p95 = per_scenario("p95_ms")
    rps = per_scenario("rps")
    fails = per_scenario("fail_ratio_pct")
    cpu = per_scenario("server_cpu_mean")

    grouped_bars(p95, scenarios, "p95 response time (ms, log scale)", "p95 response time by scenario",
                 out / "p95_by_scenario.png", log=True)
    grouped_bars(rps, scenarios, "requests per second", "Achieved throughput by scenario",
                 out / "throughput_by_scenario.png")

    if "endurance" in scenarios:
        lines({v: history(d, "endurance")[:2] for v, d in zip(summaries, dirs)},
              "minutes", "p95 (ms, log scale)", "Endurance: p95 over time", out / "endurance_p95.png", log=True)
        lines({v: memory(d, "endurance") for v, d in zip(summaries, dirs)},
              "minutes", "API process RSS (MB)", "Endurance: API memory over time", out / "endurance_memory.png")
    if "stress" in scenarios:
        lines({v: history(d, "stress")[:2] for v, d in zip(summaries, dirs)},
              "minutes (users step 50 to 100)", "p95 (ms, log scale)", "Stress: p95 as users increase",
              out / "stress_p95.png", log=True)

    variants = list(summaries)
    md = ["# Variant comparison", "",
          "Medians across runs. Response times in ms.", "",
          "| Scenario | Metric | " + " | ".join(variants) + " |",
          "|---|---|" + "---|" * len(variants)]
    for s in scenarios:
        for label, data, f in (("p95 ms", p95, "{:,.0f}"), ("requests/s", rps, "{:,.1f}"),
                               ("failures %", fails, "{:,.2f}"), ("server CPU mean %", cpu, "{:,.0f}")):
            vals = [data[v].get(s) for v in variants]
            md.append(f"| {s} | {label} | " + " | ".join("n/a" if x is None else f.format(x) for x in vals) + " |")
    md += ["", "Charts: " + ", ".join(f"`{p.name}`" for p in sorted(out.glob('*.png')))]
    (out / "comparison.md").write_text("\n".join(md) + "\n")
    print(f"Wrote {out / 'comparison.md'} and {len(list(out.glob('*.png')))} charts")


if __name__ == "__main__":
    main()
