"""Step-load shape for the stress test: start at 50 users and add 10 per step up to 100.

Loaded together with the user behaviour:
    locust -f loadtest/locustfile.py,loadtest/stress_shape.py --headless ...

STRESS_START, STRESS_END, STRESS_STEP and STRESS_TOTAL_S (total run length in
seconds) override the defaults. The step length is spread evenly over the run.
"""

from __future__ import annotations

import os

from locust import LoadTestShape

START = int(os.getenv("STRESS_START", "50"))
END = int(os.getenv("STRESS_END", "100"))
STEP = int(os.getenv("STRESS_STEP", "10"))
TOTAL_S = int(os.getenv("STRESS_TOTAL_S", "300"))


class StepStress(LoadTestShape):
    n_steps = (END - START) // STEP + 1           # 50, 60, 70, 80, 90, 100
    step_s = TOTAL_S / n_steps

    def tick(self):
        t = self.get_run_time()
        if t >= TOTAL_S:
            return None
        step = int(t // self.step_s)
        return min(START + step * STEP, END), 10   # (users, spawn rate per second)
