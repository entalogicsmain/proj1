import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from freelance_agent.app import build
from freelance_agent.router import MockProvider

ROOT = Path(__file__).resolve().parent.parent
NOON = datetime(2026, 10, 14, 12, 0)


@pytest.fixture
def make_app(tmp_path):
    def _make(handler=None, caps: dict | None = None):
        cfg_dir = tmp_path / "config"
        shutil.copytree(ROOT / "config", cfg_dir)
        shutil.copytree(ROOT / "prompts", tmp_path / "prompts")
        if caps:
            txt = (cfg_dir / "config.toml").read_text()
            for k, v in caps.items():
                import re
                txt = re.sub(rf"^{k} = .*$", f"{k} = {v}", txt, flags=re.M)
            (cfg_dir / "config.toml").write_text(txt)
        app = build(cfg_dir / "config.toml", dry_run=True, db_path=":memory:",
                    providers={"mock": MockProvider(handler)})
        return app
    return _make


def add_lead(app, score=8, contact="a@example.com", url="https://x/1"):
    return app.db.insert("leads", source="hn", url=url, summary="need a script", score=score, contact=contact,
                         status="scored", created_at=0)
