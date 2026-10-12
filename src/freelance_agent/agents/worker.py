from __future__ import annotations

import json

from ..prompts import Prompts
from ..router import ModelRouter


class Worker:
    def __init__(self, router: ModelRouter, prompts: Prompts, profile: dict):
        self.router, self.prompts, self.profile = router, prompts, profile

    def score_lead(self, lead: dict) -> dict:
        user = json.dumps({"source": lead["source"], "text": lead["summary"][:2000]})
        out = self.router.call_json("worker_cheap", "worker", "score_lead",
                                    self.prompts.get("scorer"), user, max_tokens=300)
        out["score"] = max(1.0, min(10.0, float(out.get("score", 1))))
        return out

    def draft_pitch(self, lead: dict, fix_notes: list[str] | None = None, previous: str | None = None) -> dict:
        user = json.dumps({"lead": {k: lead.get(k) for k in ("source", "summary", "need", "url")},
                           "owner_profile": self.profile,
                           "template": self.prompts.get("pitch_template_v1"),
                           "previous_draft": previous, "fix_notes": fix_notes or []})
        out = self.router.call_json("worker_write", "worker", "draft_pitch",
                                    self.prompts.get("worker"), user, max_tokens=500)
        out.setdefault("risk_flags", [])
        out["type"] = out.get("type", "pitch")
        return out
