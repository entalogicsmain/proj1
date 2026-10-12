from __future__ import annotations

import json
import time

from ..db import DB
from ..prompts import Prompts
from ..router import ModelRouter


class Questioner:
    def __init__(self, router: ModelRouter, prompts: Prompts, db: DB):
        self.router, self.prompts, self.db = router, prompts, db

    def daily_summary(self) -> dict:
        since = time.time() - 86400
        q = lambda sql: self.db.one(sql, (since,))["c"]
        return {
            "sent": q("SELECT COUNT(*) c FROM messages WHERE status='sent' AND sent_at>=?"),
            "judge_blocks": q("SELECT COUNT(*) c FROM judgments WHERE verdict='block' AND created_at>=?"),
            "judge_fixes": q("SELECT COUNT(*) c FROM judgments WHERE verdict='fix' AND created_at>=?"),
            "approvals_rejected": q("SELECT COUNT(*) c FROM approvals WHERE decision='reject' AND requested_at>=?"),
            "spend": self.db.one("SELECT COALESCE(SUM(cost),0) c FROM runs WHERE created_at>=?", (since,))["c"],
        }

    def run_daily(self) -> dict:
        summary = self.daily_summary()
        out = self.router.call_json("questioner", "questioner", "questioner", self.prompts.get("questioner"),
                                    json.dumps(summary), max_tokens=500)
        for qn in out.get("questions", []):
            self.db.insert("questions", date=time.strftime("%Y-%m-%d"), question=qn, worker_answer=None,
                           flag_raised=1 if out.get("flags") else 0)
        return out
