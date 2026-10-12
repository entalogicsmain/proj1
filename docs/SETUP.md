# Owner setup

1. Python 3.11+, `pip install -e .[dev]`, run `pytest` (all should pass).
2. Secrets (Windows Credential Manager via `pip install keyring`, or environment variables):
   `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`, `GMAIL_ADDRESS`.
3. Review `config/policy.toml` and `config/config.toml` (caps, prices, models).
4. Log in to Claude Code once on the PC with the Max plan. Do not set `ANTHROPIC_API_KEY` for it.
5. Dry run first: `fa cycle morning`, `fa cycle midday`, `fa report`. Then add `--live` with a low pitch cap.
6. Stop everything any time: `fa kill`. Resume: `fa resume`.
7. Schedule the cycles with Windows Task Scheduler (morning, midday, daily-review).
