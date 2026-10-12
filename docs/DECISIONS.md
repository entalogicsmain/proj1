# Decisions on the open questions (made while the owner was away; change any of them in config)

1. **Niche:** small Python automation scripts and bug fixes for small startups. Easiest to test and deliver with Claude Code, quick to scope, fits a $150-$600 range.
2. **Hosting:** the scheduler and orchestrator are plain Python, so they run on the Windows PC or a small cloud box unchanged. Claude Code and LinkedIn stay on the PC. Start on the PC.
3. **Sending address:** a separate sending address is recommended so a cold-email flag cannot hit the owner's main mailbox. The code only needs the four `GMAIL_*` secrets.
4. **Judge default:** DeepSeek V4 Pro, so it differs from the Worker (Claude). Switch in `[models.judge]`.
5. **Caps at launch:** 15 pitches/day, 3 LinkedIn/day, $5/day and $500 total spend, send window 09:00-17:00.
6. **Manager policy:** price $150-$600, 50% deposit, max 7 days, 2 revisions, max 2 open jobs, 1 new job/day, $1500 total exposure. Banned: guarantees, unlimited revisions, ranking promises, "within N hours". Owner must review `config/policy.toml` before going live.
7. **DeepSeek data:** only public lead text and public posts. No client code or private client data goes to DeepSeek (it is only used for scoring, the Judge on outgoing text, and the Questioner).
8. **Payments/contracts:** Stripe invoices plus an e-sign tool, owner authorizes once. Not integrated yet.
9. **LinkedIn automation not built.** Automating the owner's logged-in account risks a ban of their main professional account and breaches LinkedIn's terms. Left out until the owner explicitly accepts that risk.
10. **Model prices in `config.toml` are placeholders.** Verify before launch; spend caps use them.

Unverified: Claude Code CLI flags in `tools/claude_code.py` and the Gmail sender have not been run against live services from this environment.
