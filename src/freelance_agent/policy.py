"""Manager policy: loaded once from the owner's file; enforced in code, not just in prompts."""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Decision:
    decision: str            # approve | reject | counter
    rule: str
    terms: dict
    decided_by: str = "policy"


class Policy:
    def __init__(self, raw: dict):
        self.raw = raw
        self.banned = [re.compile(p, re.I) for p in raw["banned_promises"]["patterns"]]

    @classmethod
    def load(cls, path: str | Path) -> "Policy":
        with open(path, "rb") as f:
            return cls(tomllib.load(f))

    def banned_hits(self, text: str) -> list[str]:
        return [p.pattern for p in self.banned if p.search(text)]

    def evaluate(self, req: dict, open_commitments: int = 0, daily_new: int = 0,
                 total_value: float = 0.0) -> Decision:
        """Deterministic policy check for a deal request: {price, duration_days, type, revisions, text}.

        Returns reject/counter/approve. The LLM Manager can only narrow this, never widen it.
        """
        r = self.raw
        text = req.get("text", "") or ""
        hits = self.banned_hits(text)
        if hits:
            return Decision("reject", "banned_promises", {"patterns": hits})
        typ = (req.get("type") or "").lower()
        if typ not in [t.lower() for t in r["scope"]["allowed_types"]]:
            return Decision("reject", "scope.allowed_types", {"type": typ})
        lim = r["limits"]
        if open_commitments >= lim["max_open_commitments"]:
            return Decision("reject", "limits.max_open_commitments", {})
        if daily_new >= lim["max_daily_new_commitments"]:
            return Decision("reject", "limits.max_daily_new_commitments", {})
        price = float(req.get("price", 0))
        if total_value + price > lim["max_total_commitment_value"]:
            return Decision("reject", "limits.max_total_commitment_value", {})
        days = int(req.get("duration_days", 0))
        if days > r["scope"]["max_duration_days"]:
            return Decision("reject", "scope.max_duration_days", {"max": r["scope"]["max_duration_days"]})
        lo, hi = r["price"]["min_project"], r["price"]["max_project"]
        revisions = int(req.get("revisions", r["scope"]["max_revisions"]))
        terms = {"price": price, "duration_days": days, "type": typ,
                 "deposit": round(price * r["price"]["deposit_percent"] / 100, 2),
                 "revisions": min(revisions, r["scope"]["max_revisions"])}
        if price > hi:
            return Decision("reject", "price.max_project", {"max": hi})   # oversized: do not counter up-scope
        if price < lo:
            terms.update(price=lo, deposit=round(lo * r["price"]["deposit_percent"] / 100, 2))
            return Decision("counter", "price.min_project", terms)
        if revisions > r["scope"]["max_revisions"]:
            return Decision("counter", "scope.max_revisions", terms)
        return Decision("approve", "within_policy", terms)

    def message_ok(self, text: str) -> tuple[bool, list[str]]:
        hits = self.banned_hits(text)
        return (not hits, hits)


# Text that signals price / deadline / promise content, so the send gate requires a stored approval.
GATED = re.compile(
    r"(\$\s?\d|\b\d+\s?(usd|dollars?|eur|gbp)\b|\bprice\b|\bquote\b|\bcost[s]?\b|\bdeposit\b|\binvoice\b|"
    r"\bfee\b|\brate\b|\bdeadline\b|\bdelivered?\s+(by|in|within)\b|\bwithin\s+\d+\s*(day|week|hour)s?\b|"
    r"\bby\s+(monday|tuesday|wednesday|thursday|friday|tomorrow)\b|\bguarantee|\bpromise\b|\brefund\b)", re.I)


def needs_manager_approval(text: str) -> bool:
    return bool(GATED.search(text))
