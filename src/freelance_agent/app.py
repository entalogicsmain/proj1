"""Wiring: build the full object graph from config."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .agents.judge import Judge
from .agents.manager import Manager
from .agents.questioner import Questioner
from .agents.worker import Worker
from .config import Config, load_config
from .costs import SpendTracker
from .db import DB
from .killswitch import KillSwitch
from .orchestrator import Orchestrator
from .policy import Policy
from .prompts import Prompts
from .router import MockProvider, ModelRouter
from .tools.mail import DryRunSender, GmailSender


@dataclass
class App:
    cfg: Config
    db: DB
    kill: KillSwitch
    spend: SpendTracker
    router: ModelRouter
    policy: Policy
    worker: Worker
    judge: Judge
    manager: Manager
    questioner: Questioner
    orch: Orchestrator


def build(config_path: str | Path = "config/config.toml", dry_run: bool = True, db_path: str | None = None,
          providers: dict | None = None, profile: dict | None = None) -> App:
    cfg = load_config(config_path)
    if dry_run:  # route every role to the offline mock so nothing is spent or sent
        for spec in cfg.models.values():
            spec.provider = "mock"
    db = DB(db_path or cfg.path("db"))
    kill = KillSwitch(db, cfg.path("kill_file"))
    spend = SpendTracker(db, cfg)
    router = ModelRouter(cfg, db, spend, kill, providers=providers)
    if dry_run and providers is None:
        router.providers["mock"] = MockProvider()
    policy = Policy.load(cfg.path("policy"))
    prompts = Prompts(cfg.path("prompts"))
    profile = profile or {"name": "the owner", "skills": ["Python", "automation scripts", "bug fixes"],
                          "note": "Fill in real experience in config; the Worker may not claim anything else."}
    worker = Worker(router, prompts, profile)
    judge = Judge(router, prompts, policy, db)
    manager = Manager(router, prompts, policy, db)
    questioner = Questioner(router, prompts, db)
    sender = DryRunSender() if dry_run else GmailSender()
    orch = Orchestrator(cfg, db, kill, policy, worker, judge, manager, sender)
    return App(cfg, db, kill, spend, router, policy, worker, judge, manager, questioner, orch)
