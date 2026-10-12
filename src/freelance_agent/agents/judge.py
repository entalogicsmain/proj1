"""Judge: fast rule checks first (cheap, deterministic), then an LLM checklist on a different model."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from ..db import DB
from ..policy import Policy
from ..prompts import Prompts
from ..router import ModelRouter

SPAM_PATTERNS = [r"act now", r"limited time", r"!!+", r"100% free", r"click here", r"dear sir", r"\bguaranteed\b",
                 r"make money", r"urgent!!", r"\bbuy now\b"]
MIN_PASS = 4


@dataclass
class Verdict:
    verdict: str                      # pass | fix | block
    scores: dict = field(default_factory=dict)
    fixes: list[str] = field(default_factory=list)
    reason: str = ""


class Judge:
    def __init__(self, router: ModelRouter, prompts: Prompts, policy: Policy, db: DB):
        self.router, self.prompts, self.policy, self.db = router, prompts, policy, db

    def rule_check(self, text: str, require_optout: bool = True) -> Verdict | None:
        ok, hits = self.policy.message_ok(text)
        if not ok:
            return Verdict("block", reason=f"banned promise pattern: {hits}")
        for p in SPAM_PATTERNS:
            if re.search(p, text, re.I):
                return Verdict("block", reason=f"spam-like text: {p}")
        if len(text) > 1200:
            return Verdict("fix", fixes=["Shorten to under 1200 characters"], reason="too long")
        if require_optout and not re.search(r"(opt.?out|won'?t write again|unsubscribe|reply stop)", text, re.I):
            return Verdict("fix", fixes=["Add a simple opt-out line"], reason="missing opt-out")
        return None

    def review(self, item_type: str, item_id: int, text: str, context: dict | None = None,
               round_no: int = 1, require_optout: bool = True) -> Verdict:
        v = self.rule_check(text, require_optout)
        model = self.router.cfg.model("judge").model
        if v is None:
            out = self.router.call_json("judge", "judge", "judge", self.prompts.get("judge"),
                                        json.dumps({"item_type": item_type, "text": text, "context": context or {}}),
                                        max_tokens=400)
            scores = out.get("scores", {})
            verdict = out.get("verdict", "block")
            # The Judge cannot pass an item that scores under the bar, whatever the model says.
            if verdict == "pass" and (not scores or min(scores.values()) < MIN_PASS):
                verdict = "fix"
            v = Verdict(verdict, scores, list(out.get("fixes", [])), out.get("reason", ""))
        self.db.insert("judgments", item_type=item_type, item_id=item_id, scores=json.dumps(v.scores),
                       verdict=v.verdict, fix_notes=json.dumps(v.fixes + ([v.reason] if v.reason else [])),
                       round=round_no, model_used=model, created_at=time.time())
        return v
