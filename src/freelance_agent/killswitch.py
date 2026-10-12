"""Kill switch: a file flag plus a DB flag. Either one stops every scheduler and send."""
from __future__ import annotations

import time
from pathlib import Path

from .db import DB


class Killed(RuntimeError):
    pass


class KillSwitch:
    def __init__(self, db: DB, kill_file: Path):
        self.db = db
        self.kill_file = Path(kill_file)

    def is_active(self) -> bool:
        return self.kill_file.exists() or self.db.get_state("killed") == "1"

    def engage(self, reason: str = "manual"):
        self.kill_file.parent.mkdir(parents=True, exist_ok=True)
        self.kill_file.write_text(f"{time.time()} {reason}\n")
        self.db.set_state("killed", "1")
        # revoke anything queued for sending
        self.db.execute("UPDATE messages SET status='revoked' WHERE status IN ('drafted','approved','queued')")
        self.db.execute("UPDATE tasks SET state='blocked', error='kill switch' WHERE state IN ('queued','running')")
        self.db.event("kill_switch", reason=reason)

    def release(self):
        if self.kill_file.exists():
            self.kill_file.unlink()
        self.db.set_state("killed", "0")
        self.db.event("kill_switch_released")

    def check(self):
        if self.is_active():
            raise Killed("kill switch is engaged")
