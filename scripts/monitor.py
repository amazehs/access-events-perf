"""Sample CPU and memory of selected processes to a CSV file until stopped.

    python scripts/monitor.py --pid server=12345 --pid locust=12346 --out monitor.csv

cpu_percent is per process and can exceed 100 on multi-core machines
(100 = one full core). system_cpu_percent is the whole machine, 0 to 100.
"""

from __future__ import annotations

import argparse
import csv
import signal
import time

import psutil

running = True


def _stop(*_):
    global running
    running = False


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--pid", action="append", required=True, help="label=PID, repeatable")
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--out", required=True)
    a = p.parse_args()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    procs = {}
    for item in a.pid:
        label, pid = item.split("=")
        proc = psutil.Process(int(pid))
        proc.cpu_percent(None)  # prime the counter; the first reading is always 0
        procs[label] = proc
    psutil.cpu_percent(None)

    start = time.time()
    with open(a.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["elapsed_s", "process", "cpu_percent", "rss_mb", "threads", "system_cpu_percent"])
        while running and procs:
            time.sleep(a.interval)
            sys_cpu = psutil.cpu_percent(None)
            elapsed = round(time.time() - start, 1)
            for label, proc in list(procs.items()):
                try:
                    with proc.oneshot():
                        w.writerow([elapsed, label, proc.cpu_percent(None),
                                    round(proc.memory_info().rss / 2**20, 1), proc.num_threads(), sys_cpu])
                except psutil.Error:
                    procs.pop(label)  # process exited
            f.flush()


if __name__ == "__main__":
    main()
