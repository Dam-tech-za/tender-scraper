"""python -m tender_scout scrape | digest | dashboard"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

from tender_scout.config import get_settings


def _logging() -> None:
    logging.basicConfig(
        level=get_settings().log_level.upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def cmd_scrape(args: argparse.Namespace) -> int:
    from tender_scout.pipeline import run_scrape

    _, summary = run_scrape()
    print(json.dumps(asdict(summary), indent=1))
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    from tender_scout import dashboard
    from tender_scout.store import JsonStore

    tenders, meta = JsonStore(get_settings().data_dir).load_tenders()
    path = dashboard.write(tenders, meta, Path(args.out))
    print(f"Dashboard written to {path} ({len(tenders)} tenders)")
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    from tender_scout import dashboard, digest
    from tender_scout.store import JsonStore

    settings = get_settings()
    store = JsonStore(settings.data_dir)
    tenders, meta = store.load_tenders()
    store.apply_state(tenders)  # pick up notified_at from state.json
    groups = digest.select(tenders, min_band=digest.min_band())
    body = digest.render_html(groups, total_relevant=len(tenders), dashboard_url=settings.dashboard_url)
    subject = digest.subject_for(groups)
    if args.print_html:
        print(body)
    if not args.send:
        print(f"[dry run] {subject}")
        return 0
    if not settings.email_configured():
        msg = "Email is not configured (set EMAIL_FROM, EMAIL_TO and RESEND_API_KEY or SMTP_HOST secrets); digest skipped."
        print(f"::warning::{msg}" if settings.env == "github" else msg, file=sys.stderr)
        return 0
    if not any(groups.values()) and not args.always:
        print("Nothing new to send.")
        return 0
    attachment = ("damtech-tenders.html", dashboard.render(tenders, meta).encode("utf-8"))
    digest.send(subject, body, attachment=attachment, settings=settings)
    # Only mark as notified after a successful send.
    store.mark_notified(groups["new"])
    store.save_state()
    print(f"Sent: {subject}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tender-scout", description="South African tender monitor for Damtech")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scrape", help="Fetch, score and save open tenders").set_defaults(fn=cmd_scrape)
    d = sub.add_parser("dashboard", help="Build the static dashboard from data/tenders.json")
    d.add_argument("--out", default="site")
    d.set_defaults(fn=cmd_dashboard)
    g = sub.add_parser("digest", help="Build (and optionally send) the email digest")
    g.add_argument("--send", action="store_true", help="Actually send the email")
    g.add_argument("--always", action="store_true", help="Send even when there is nothing new")
    g.add_argument("--print-html", action="store_true")
    g.set_defaults(fn=cmd_digest)
    args = parser.parse_args(argv)
    _logging()
    try:
        return args.fn(args)
    except Exception:
        logging.getLogger("tender_scout").exception("%s failed", args.command)
        return 1


if __name__ == "__main__":
    sys.exit(main())
