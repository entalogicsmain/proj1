"""Weekly report built straight from the log."""
from __future__ import annotations

import time

from .db import DB


def weekly_report(db: DB, days: int = 7) -> str:
    since = time.time() - days * 86400
    one = lambda sql, *p: db.one(sql, p)
    sent = one("SELECT COUNT(*) c FROM messages WHERE status='sent' AND sent_at>=?", since)["c"]
    replies = one("SELECT COUNT(*) c FROM messages WHERE reply_at IS NOT NULL AND sent_at>=?", since)["c"]
    leads7 = one("SELECT COUNT(*) c FROM leads WHERE score>=7 AND created_at>=?", since)["c"]
    judged = one("SELECT COUNT(*) c FROM judgments WHERE round=1 AND item_type='pitch' AND created_at>=?", since)["c"]
    passed = one("SELECT COUNT(*) c FROM judgments WHERE round=1 AND item_type='pitch' AND verdict='pass' "
                 "AND created_at>=?", since)["c"]
    spend = one("SELECT COALESCE(SUM(cost),0) c FROM runs WHERE created_at>=?", since)["c"]
    total = one("SELECT COALESCE(SUM(cost),0) c FROM runs")["c"]
    won = one("SELECT COUNT(*) c FROM jobs WHERE paid_at IS NOT NULL")["c"]
    by_tpl = db.all("SELECT template_version v, COUNT(*) n, SUM(reply_at IS NOT NULL) r FROM messages "
                    "WHERE status='sent' AND sent_at>=? GROUP BY template_version", (since,))
    by_agent = db.all("SELECT agent, COUNT(*) n, ROUND(SUM(cost),4) c FROM runs WHERE created_at>=? GROUP BY agent",
                      (since,))
    pct = lambda a, b: f"{100 * a / b:.1f}%" if b else "n/a"
    lines = [f"# Weekly report (last {days} days)", "",
             f"- Pitches sent: {sent}", f"- Replies: {replies} (reply rate {pct(replies, sent)})",
             f"- Leads scoring 7+: {leads7}", f"- Judge first-pass rate: {pct(passed, judged)}",
             f"- Spend this week: ${spend:.2f}; total: ${total:.2f}",
             f"- Cost per won client: " + (f"${total / won:.2f}" if won else "n/a (no paid jobs yet)"), "",
             "## By pitch template"]
    lines += [f"- {r['v']}: {r['n']} sent, {r['r'] or 0} replies" for r in by_tpl] or ["- none"]
    lines += ["", "## Spend by agent"] + [f"- {r['agent']}: {r['n']} calls, ${r['c']}" for r in by_agent] or ["- none"]
    return "\n".join(lines)
