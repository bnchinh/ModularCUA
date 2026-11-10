from __future__ import annotations

import time


class BudgetController:
    def __init__(self, max_steps: int, max_wall_seconds: float):
        self.max_steps = max_steps
        self.max_wall_seconds = max_wall_seconds
        self.started = time.monotonic()

    def stop_reason(self, next_step: int) -> str | None:
        if next_step > self.max_steps:
            return "model_step_budget_exhausted"
        if time.monotonic() - self.started >= self.max_wall_seconds:
            return "wall_clock_budget_exhausted"
        return None
