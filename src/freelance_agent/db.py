"""Local SQLite store. Schema follows section 8 of the scope, plus control tables."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
  id INTEGER PRIMARY KEY, source TEXT, url TEXT UNIQUE, summary TEXT, need TEXT,
  budget_hint TEXT, urgency TEXT, contact TEXT, score REAL, status TEXT DEFAULT 'new',
  created_at REAL
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY, lead_id INTEGER, direction TEXT, channel TEXT, draft TEXT,
  final_text TEXT, template_version TEXT, kind TEXT, idem_key TEXT UNIQUE,
  status TEXT DEFAULT 'drafted', sent_at REAL, reply_at REAL, created_at REAL
);
CREATE TABLE IF NOT EXISTS judgments (
  id INTEGER PRIMARY KEY, item_type TEXT, item_id INTEGER, scores TEXT, verdict TEXT,
  fix_notes TEXT, round INTEGER, model_used TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY, item_type TEXT, item_id INTEGER, requested_at REAL,
  decision TEXT, decided_by TEXT, rule_applied TEXT, terms TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY, lead_id INTEGER, scope TEXT, price REAL, deposit_status TEXT,
  repo_link TEXT, status TEXT DEFAULT 'queued', delivered_at REAL, paid_at REAL,
  created_at REAL
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY, agent TEXT, task TEXT, model TEXT, tokens_in INTEGER,
  tokens_out INTEGER, cost REAL, duration REAL, error TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS questions (
  id INTEGER PRIMARY KEY, date TEXT, question TEXT, worker_answer TEXT, flag_raised INTEGER
);
CREATE TABLE IF NOT EXISTS experiments (
  id INTEGER PRIMARY KEY, niche TEXT, pitch_version TEXT, send_hour INTEGER,
  sample_size INTEGER, reply_rate REAL, created_at REAL
);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY, kind TEXT, payload TEXT, state TEXT DEFAULT 'queued',
  attempts INTEGER DEFAULT 0, not_before REAL DEFAULT 0, error TEXT, created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS optouts (email TEXT PRIMARY KEY, reason TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, kind TEXT, detail TEXT, created_at REAL
);
"""

TASK_STATES = ("queued", "running", "needs_approval", "blocked", "done", "failed")


class DB:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur

    def one(self, sql: str, params: tuple = ()):
        return self.conn.execute(sql, params).fetchone()

    def all(self, sql: str, params: tuple = ()):
        return self.conn.execute(sql, params).fetchall()

    def insert(self, table: str, **fields) -> int:
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        return self.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})",
                            tuple(fields.values())).lastrowid

    def event(self, kind: str, **detail):
        self.insert("events", kind=kind, detail=json.dumps(detail, default=str), created_at=time.time())

    def get_state(self, key: str, default: str | None = None) -> str | None:
        r = self.one("SELECT value FROM state WHERE key=?", (key,))
        return r["value"] if r else default

    def set_state(self, key: str, value: str):
        self.execute("INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (key, value))

    def close(self):
        self.conn.close()
