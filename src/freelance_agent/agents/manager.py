"""Manager: policy decides first (code), the LLM may only narrow, never widen."""
from __future__ import annotations

import json
import time

from ..db import DB
from ..policy import Decision, Policy
from ..prompts import Prompts
from ..router import ModelRouter, ProviderError

RANK = {"approve": 2, "counter": 1, "reject": 0}


class Manager:
    def __init__(self, router: ModelRouter, prompts: Prompts, policy: Policy, db: DB):
        self.router, self.prompts, self.policy, self.db = router, prompts, policy, db

    def _commitments(self) -> tuple[int, int, float]:
        open_n = self.db.one("SELECT COUNT(*) c FROM jobs WHERE status IN ('queued','running','signed')")["c"]
        start = time.time() - (time.time() % 86400)
        daily = self.db.one("SELECT COUNT(*) c FROM jobs WHERE created_at>=?", (start,))["c"]
        value = self.db.one("SELECT COALESCE(SUM(price),0) c FROM jobs WHERE status IN ('queued','running','signed')")["c"]
        return open_n, daily, value

    def decide_deal(self, item_type: str, item_id: int, req: dict, money: bool = True) -> Decision:
        base = self.policy.evaluate(req, *self._commitments())
        final = base
        if base.decision != "reject":
            try:
                out = self.router.call_json("manager_money" if money else "manager_routine", "manager", "manager",
                                            self.prompts.get("manager"),
                                            json.dumps({"request": req, "policy_check": base.__dict__,
                                                        "policy": self.policy.raw}), max_tokens=400)
                llm = Decision(out.get("decision", "reject"), out.get("rule", "llm"), out.get("terms", {}), "manager_llm")
                if llm.decision not in RANK:
                    llm = Decision("reject", "invalid_llm_output", {}, "manager_llm")
                # LLM may narrow (reject/counter), never widen beyond the policy result.
                if RANK[llm.decision] < RANK[base.decision]:
                    final = llm
                    if llm.decision == "counter":
                        final.terms = {**base.terms, **{k: v for k, v in llm.terms.items() if k in ("price", "deposit")}}
                        final = self.policy_clamp(final, req)
            except ProviderError:
                final = Decision("reject", "manager_unavailable", {}, "policy")
        return self.record(item_type, item_id, final)

    def policy_clamp(self, d: Decision, req: dict) -> Decision:
        """A counter from the LLM must itself pass policy; otherwise reject."""
        check = self.policy.evaluate({**req, "price": d.terms.get("price", req.get("price", 0))},
                                     *self._commitments())
        if check.decision == "reject":
            return Decision("reject", check.rule, {}, d.decided_by)
        d.terms = check.terms
        return d

    def decide_message(self, item_type: str, item_id: int, text: str) -> Decision:
        """Approve a message that touches price/deadline/promise. Banned content is always rejected."""
        ok, hits = self.policy.message_ok(text)
        d = Decision("approve", "message_within_policy", {}) if ok else Decision("reject", "banned_promises", {"hits": hits})
        return self.record(item_type, item_id, d)

    def record(self, item_type: str, item_id: int, d: Decision) -> Decision:
        self.db.insert("approvals", item_type=item_type, item_id=item_id, requested_at=time.time(),
                       decision=d.decision, decided_by=d.decided_by, rule_applied=d.rule,
                       terms=json.dumps(d.terms))
        return d

    def has_approval(self, item_type: str, item_id: int) -> bool:
        r = self.db.one("SELECT decision FROM approvals WHERE item_type=? AND item_id=? ORDER BY id DESC LIMIT 1",
                        (item_type, item_id))
        return bool(r and r["decision"] == "approve")
