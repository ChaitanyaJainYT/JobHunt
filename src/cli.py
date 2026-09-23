"""argparse wiring. Smart defaults: bare URL -> apply, --check-mail -> check-mail."""
from __future__ import annotations

import argparse


def looks_like_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agent.py",
        description="Local Automated Job Application Assistant. Example: python agent.py \"<job-url>\"",
    )
    p.add_argument("--demo", "--mock", dest="demo", action="store_true",
                   help="Offline trial with fixtures, no API keys needed.")
    p.add_argument("--check-mail", dest="check_mail_flag", action="store_true",
                   help="Shortcut for 'check-mail' subcommand.")

    sub = p.add_subparsers(dest="command")

    a = sub.add_parser("apply", help="Prepare tailored resume + log to sheet (does NOT auto-apply).")
    a.add_argument("--url", "-u", help="Job posting URL.")
    a.add_argument("url_pos", nargs="?", help="Job URL (positional).")
    a.add_argument("--out", help="Custom output dir (default: output/<Company>_<JobId>/).")
    a.add_argument("--resume", action="store_true",
                   help="Reuse saved job.json+match.json (skips fetch+match LLM calls).")
    a.add_argument("--demo", dest="demo", action="store_true", help="Offline trial.")

    c = sub.add_parser("check-mail", help="Scan Gmail for employer replies, update sheet.")
    c.add_argument("--days", type=int, default=14, help="Lookback window (default 14).")
    c.add_argument("--demo", dest="demo", action="store_true", help="Use fixture emails.")

    sub.add_parser("doctor", help="Health check: python, tectonic, .env, resume, Google creds.")
    sub.add_parser("setup", help="Interactive .env wizard.")
    return p


def normalize_args(argv=None) -> argparse.Namespace:
    import sys
    raw = list(sys.argv[1:] if argv is None else argv)
    # Pre-process: bare URL shortcut -> apply --url <url>
    # e.g. python agent.py "https://..."  or  python agent.py --demo "https://..."
    subcommands = {"apply", "check-mail", "doctor", "setup"}
    has_sub = any(a in subcommands for a in raw)
    urls = [a for a in raw if looks_like_url(a)]
    if urls and not has_sub:
        url = urls[0]
        rest = [a for a in raw if a != url]
        # preserve --demo/--mock/--check-mail flags, drop bare handling
        raw = ["apply", "--url", url] + rest
    parser = build_parser()
    ns = parser.parse_args(raw)
    # --check-mail flag without subcommand
    if getattr(ns, "check_mail_flag", False) and not ns.command:
        ns.command = "check-mail"
        if not hasattr(ns, "days"):
            ns.days = 14
    if ns.command == "apply":
        url = getattr(ns, "url", None) or getattr(ns, "url_pos", None)
        ns.url = url
        if not url:
            parser.error("apply needs a job URL. Example: python agent.py \"https://www.linkedin.com/jobs/view/123\"")
    return ns
