"""Lead intake and scoring."""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Callable

from .agents.worker import Worker
from .db import DB

HN_QUERIES = ["looking for a developer", "need a freelancer", "hiring freelance developer"]


def http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "freelance-agent/0.1 (contact owner)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def collect_hn(fetch: Callable[[str], dict] = http_get_json, limit: int = 20) -> list[dict]:
    """Public HN Algolia search. Respect rate limits: one call per query, results cached by URL uniqueness."""
    out = []
    for q in HN_QUERIES:
        url = ("https://hn.algolia.com/api/v1/search_by_date?tags=comment&hitsPerPage=%d&query=%s"
               % (limit, urllib.parse.quote(q)))
        for h in fetch(url).get("hits", []):
            text = (h.get("comment_text") or "")[:2000]
            if text:
                out.append({"source": "hn", "url": f"https://news.ycombinator.com/item?id={h['objectID']}",
                            "summary": text})
    return out


def ingest(db: DB, leads: list[dict]) -> int:
    n = 0
    for l in leads:
        if db.one("SELECT 1 FROM leads WHERE url=?", (l["url"],)):
            continue
        db.insert("leads", source=l["source"], url=l["url"], summary=l["summary"],
                  contact=l.get("contact"), created_at=time.time())
        n += 1
    return n


def score_pending(db: DB, worker: Worker, limit: int = 50) -> int:
    rows = db.all("SELECT * FROM leads WHERE score IS NULL ORDER BY id LIMIT ?", (limit,))
    for r in rows:
        s = worker.score_lead(dict(r))
        db.execute("UPDATE leads SET score=?, need=?, budget_hint=?, urgency=?, status='scored' WHERE id=?",
                   (s["score"], s.get("need"), s.get("budget_hint"), s.get("urgency"), r["id"]))
    return len(rows)
