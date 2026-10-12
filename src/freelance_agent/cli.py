"""`fa` command line: status, kill switch, dry-run cycles, report."""
from __future__ import annotations

import argparse
import sys

from . import leads as leadmod
from .app import build
from .report import weekly_report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fa")
    ap.add_argument("--config", default="config/config.toml")
    ap.add_argument("--live", action="store_true", help="use real models and Gmail (default is dry run)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("kill")
    sub.add_parser("resume")
    c = sub.add_parser("cycle")
    c.add_argument("name", choices=["morning", "midday", "daily-review"])
    sub.add_parser("report")
    args = ap.parse_args(argv)

    app = build(args.config, dry_run=not args.live)
    if args.cmd == "kill":
        app.kill.engage("cli")
        print("Kill switch engaged. All sends revoked, tasks blocked.")
    elif args.cmd == "resume":
        app.kill.release()
        print("Kill switch released.")
    elif args.cmd == "status":
        print(f"killed={app.kill.is_active()} spend_total=${app.spend.total():.4f} "
              f"spend_today=${app.spend.today():.4f} sent_today={app.orch.sent_today('email')}")
    elif args.cmd == "report":
        print(weekly_report(app.db))
    elif args.cmd == "cycle":
        if args.name == "morning":
            n = leadmod.ingest(app.db, leadmod.collect_hn())
            s = leadmod.score_pending(app.db, app.worker)
            print(f"ingested={n} scored={s}")
        elif args.name == "midday":
            print(app.orch.midday_outreach())
        else:
            print(app.questioner.run_daily())
    return 0


if __name__ == "__main__":
    sys.exit(main())
