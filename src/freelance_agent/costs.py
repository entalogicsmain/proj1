"""Cost tracking and hard spend caps. Every model call is logged to `runs`."""
from __future__ import annotations

import time

from .config import Config
from .db import DB


class SpendCapExceeded(RuntimeError):
    pass


def compute_cost(cfg: Config, model: str, tokens_in: int, tokens_out: int) -> float:
    p = cfg.pricing.get(model)
    if not p:
        return 0.0
    return (tokens_in * p["input"] + tokens_out * p["output"]) / 1_000_000


class SpendTracker:
    def __init__(self, db: DB, cfg: Config):
        self.db = db
        self.cfg = cfg

    def total(self) -> float:
        return self.db.one("SELECT COALESCE(SUM(cost),0) c FROM runs")["c"]

    def today(self) -> float:
        start = time.time() - (time.time() % 86400)  # UTC day
        return self.db.one("SELECT COALESCE(SUM(cost),0) c FROM runs WHERE created_at>=?", (start,))["c"]

    def check_before_call(self, projected: float = 0.0):
        """Raise at 100% of a cap; log a one-time warning at the warn fraction."""
        caps = self.cfg.caps
        total, today = self.total() + projected, self.today() + projected
        if total >= caps["total_spend"]:
            self.db.set_state("paused_spend", "total")
            raise SpendCapExceeded(f"total spend cap reached: ${total:.2f}")
        if today >= caps["daily_spend"]:
            self.db.set_state("paused_spend", "daily")
            raise SpendCapExceeded(f"daily spend cap reached: ${today:.2f}")
        self._warn(total, today)

    def _warn(self, total: float, today: float):
        caps = self.cfg.caps
        warn = caps["warn_fraction"]
        if total >= warn * caps["total_spend"] or today >= warn * caps["daily_spend"]:
            if self.db.get_state("warned_day") != time.strftime("%Y-%m-%d"):
                self.db.set_state("warned_day", time.strftime("%Y-%m-%d"))
                self.db.event("spend_warning", total=total, today=today)

    def record(self, agent: str, task: str, model: str, tin: int, tout: int, duration: float,
               error: str | None = None) -> float:
        cost = compute_cost(self.cfg, model, tin, tout)
        self.db.insert("runs", agent=agent, task=task, model=model, tokens_in=tin, tokens_out=tout,
                       cost=cost, duration=duration, error=error, created_at=time.time())
        self._warn(self.total(), self.today())
        return cost
