# Autonomous Freelance Software Engineer

Four agents (Worker, Judge, Manager, Questioner) behind one orchestrator, per `Project Scope: Autonomous Freelance Software Engineer`.
Pure Python 3.11+, standard library only (pytest for tests).

## Status

| Phase | State |
| --- | --- |
| 1 Foundation: config, SQLite log, model router (Claude + DeepSeek), cost log, spend caps, kill switch | Done, tested |
| 2 Research and outreach: lead intake/scoring, Worker, Judge, Manager + policy, send gate, Gmail sender, scheduler cycles | Core done, tested offline. LinkedIn module not built (see DECISIONS.md) |
| 3 Replies, contracts, builds | Claude Code headless runner with usage-limit handling done. Reply handling, e-sign, invoices, GitHub delivery, demo portfolio not built |
| 4 Audit and tuning | Questioner daily run and weekly report done. Experiments table, dashboard, 14-day run not done |

Everything runs in dry-run mode by default (mock models, no email sent). `--live` switches to real APIs and Gmail.

## Use

```
pip install -e .[dev]
pytest
fa status | kill | resume | report
fa cycle morning | midday | daily-review
```

## Safety enforced in code (not only in prompts)

- Kill switch (file + DB flag) blocks every model call and send, and revokes queued messages.
- Send gate: opt-outs, daily cap, send window, banned-promise patterns, stored Manager approval for any price/deadline/promise text, idempotent sends.
- Manager: deterministic policy check first (`config/policy.toml`); the LLM can only narrow the result, never widen it.
- Judge: rule checks block seeded bad examples without a model; the LLM cannot pass items scoring under 4.
- Spend caps: warn at 70%, hard stop at 100% (daily and total).
- Claude Code runs in a per-job folder with API keys removed from its environment.

See `docs/DECISIONS.md` for the choices made on the open questions and `docs/SETUP.md` for owner setup.
