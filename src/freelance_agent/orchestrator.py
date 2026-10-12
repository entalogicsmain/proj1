"""Orchestrator: the only component that touches the outside world.

Every send goes through `send_message`, which enforces (in code, not prompts):
kill switch, opt-outs, daily caps, send window, banned promises, stored Manager approval for
price/deadline/promise text, and idempotency.
"""
from __future__ import annotations

import time
from datetime import datetime

from .agents.judge import Judge
from .agents.manager import Manager
from .agents.worker import Worker
from .config import Config
from .db import DB
from .killswitch import KillSwitch
from .policy import Policy, needs_manager_approval
from .tools.mail import Sender


class SendBlocked(RuntimeError):
    pass


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


class Orchestrator:
    def __init__(self, cfg: Config, db: DB, kill: KillSwitch, policy: Policy, worker: Worker, judge: Judge,
                 manager: Manager, sender: Sender, template_version: str = "v1"):
        self.cfg, self.db, self.kill, self.policy = cfg, db, kill, policy
        self.worker, self.judge, self.manager, self.sender = worker, judge, manager, sender
        self.template_version = template_version

    # ---- caps -------------------------------------------------------------------------------
    def sent_today(self, channel: str) -> int:
        start = time.time() - (time.time() % 86400)
        return self.db.one("SELECT COUNT(*) c FROM messages WHERE channel=? AND status='sent' AND sent_at>=?",
                           (channel, start))["c"]

    def in_send_window(self, now: datetime | None = None) -> bool:
        now = now or datetime.now()
        cur = now.hour * 60 + now.minute
        return _minutes(self.cfg.caps["send_window_start"]) <= cur < _minutes(self.cfg.caps["send_window_end"])

    def is_opted_out(self, email: str) -> bool:
        return self.db.one("SELECT 1 FROM optouts WHERE email=?", (email.lower(),)) is not None

    def record_optout(self, email: str, reason: str = "requested"):
        self.db.execute("INSERT OR REPLACE INTO optouts(email,reason,created_at) VALUES(?,?,?)",
                        (email.lower(), reason, time.time()))

    # ---- drafting with Judge loop -----------------------------------------------------------
    def prepare_pitch(self, lead_id: int) -> int | None:
        """Draft -> Judge (max N fix rounds) -> Manager if still unresolved. Returns message id or None if dropped."""
        lead = dict(self.db.one("SELECT * FROM leads WHERE id=?", (lead_id,)))
        key = f"{lead_id}:pitch:{self.template_version}"
        existing = self.db.one("SELECT id FROM messages WHERE idem_key=?", (key,))
        if existing:
            return existing["id"]
        max_rounds = self.cfg.caps["judge_max_fix_rounds"]
        draft = self.worker.draft_pitch(lead)
        msg_id = self.db.insert("messages", lead_id=lead_id, direction="out", channel="email", draft=draft["draft"],
                                template_version=self.template_version, kind="pitch", idem_key=key,
                                status="drafted", created_at=time.time())
        round_no, notes = 1, []
        while True:
            v = self.judge.review("pitch", msg_id, draft["draft"], {"lead_id": lead_id}, round_no)
            if v.verdict == "pass":
                break
            if v.verdict == "block":
                self.db.execute("UPDATE messages SET status='dropped' WHERE id=?", (msg_id,))
                return None
            if round_no > max_rounds:   # fixes exhausted: Manager approves or drops
                d = self.manager.decide_message("pitch", msg_id, draft["draft"])
                if d.decision != "approve" or self.judge.rule_check(draft["draft"]) is not None:
                    self.db.execute("UPDATE messages SET status='dropped' WHERE id=?", (msg_id,))
                    return None
                break
            notes = v.fixes
            draft = self.worker.draft_pitch(lead, fix_notes=notes, previous=draft["draft"])
            self.db.execute("UPDATE messages SET draft=? WHERE id=?", (draft["draft"], msg_id))
            round_no += 1
        if "needs_manager_approval" in draft.get("risk_flags", []) or needs_manager_approval(draft["draft"]):
            d = self.manager.decide_message("message", msg_id, draft["draft"])
            if d.decision != "approve":
                self.db.execute("UPDATE messages SET status='dropped' WHERE id=?", (msg_id,))
                return None
        self.db.execute("UPDATE messages SET final_text=?, status='approved' WHERE id=?", (draft["draft"], msg_id))
        return msg_id

    # ---- the send gate ----------------------------------------------------------------------
    def send_message(self, msg_id: int, to: str, subject: str = "Quick question about your project",
                     now: datetime | None = None) -> str:
        self.kill.check()
        m = self.db.one("SELECT * FROM messages WHERE id=?", (msg_id,))
        if m is None:
            raise SendBlocked("unknown message")
        if m["status"] == "sent":
            return "already-sent"                       # idempotent: a retry never double-sends
        if m["status"] != "approved" or not m["final_text"]:
            raise SendBlocked(f"message {msg_id} not approved (status={m['status']})")
        text = m["final_text"]
        if self.is_opted_out(to):
            raise SendBlocked("recipient opted out")
        ok, hits = self.policy.message_ok(text)
        if not ok:
            raise SendBlocked(f"banned promise text: {hits}")
        if needs_manager_approval(text) and not self.manager.has_approval("message", msg_id):
            raise SendBlocked("price/deadline/promise text without stored Manager approval")
        if not self.in_send_window(now):
            raise SendBlocked("outside send window")
        if m["kind"] == "pitch" and self.sent_today("email") >= self.cfg.caps["daily_pitches"]:
            raise SendBlocked("daily pitch cap reached")
        # claim the message before sending so a crash mid-send is visible, not repeated
        claimed = self.db.execute("UPDATE messages SET status='sending' WHERE id=? AND status='approved'", (msg_id,))
        if claimed.rowcount != 1:
            raise SendBlocked("message already claimed")
        try:
            ext_id = self.sender.send(to, subject, text)
        except Exception as e:
            self.db.execute("UPDATE messages SET status='failed' WHERE id=?", (msg_id,))
            self.db.event("send_failed", message=msg_id, error=str(e))
            raise
        self.db.execute("UPDATE messages SET status='sent', channel='email', sent_at=? WHERE id=?", (time.time(), msg_id))
        self.db.execute("UPDATE leads SET status='pitched' WHERE id=?", (m["lead_id"],))
        self.db.event("sent", message=msg_id, ext_id=ext_id)
        return ext_id

    # ---- daily cycles -----------------------------------------------------------------------
    def midday_outreach(self, now: datetime | None = None) -> dict:
        thr = self.cfg.caps["lead_score_threshold"]
        leads = self.db.all("SELECT * FROM leads WHERE score>=? AND status='scored' AND contact IS NOT NULL "
                            "ORDER BY score DESC", (thr,))
        stats = {"considered": len(leads), "sent": 0, "dropped": 0, "blocked": 0}
        for l in leads:
            if self.sent_today("email") >= self.cfg.caps["daily_pitches"]:
                break
            if self.is_opted_out(l["contact"]):
                continue
            mid = self.prepare_pitch(l["id"])
            if mid is None:
                stats["dropped"] += 1
                self.db.execute("UPDATE leads SET status='dropped' WHERE id=?", (l["id"],))
                continue
            try:
                self.send_message(mid, l["contact"], now=now)
                stats["sent"] += 1
            except SendBlocked as e:
                stats["blocked"] += 1
                self.db.event("send_blocked", message=mid, reason=str(e))
        return stats
