#!/usr/bin/env python3
"""Single entrypoint. Never throws raw tracebacks for user errors."""
from __future__ import annotations

import sys

from src.cli import normalize_args
from src.config import ConfigError, run_setup_wizard
from src.doctor import print_doctor, run_doctor


def main(argv=None) -> int:
    try:
        ns = normalize_args(argv)
    except SystemExit as e:
        return int(e.code or 0)

    cmd = ns.command
    demo = bool(getattr(ns, "demo", False))

    try:
        if cmd == "doctor":
            return print_doctor(run_doctor())
        if cmd == "setup":
            run_setup_wizard()
            return print_doctor(run_doctor())
        if cmd == "apply":
            from src.pipeline import run_apply
            return run_apply(ns.url, demo=demo, out=getattr(ns, "out", None),
                             resume=bool(getattr(ns, "resume", False)))
        if cmd == "check-mail":
            from src.pipeline import run_check_mail_flow
            return run_check_mail_flow(days=int(getattr(ns, "days", 14)), demo=demo)
        if cmd == "ui":
            import ui as _ui
            _ui.main(port=int(getattr(ns, "port", 8765) or 8765),
                     open_browser=not getattr(ns, "no_browser", False))
            return 0

        from src.cli import build_parser
        build_parser().print_help()
        print("\nQuickstart:")
        print("  python agent.py doctor")
        print("  python agent.py --demo \"https://www.linkedin.com/jobs/view/4012345678\"")
        print("  python agent.py setup")
        return 0
    except ConfigError as e:
        print(f"\n[ERROR] Config error: {e}")
        return 2
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {type(e).__name__}: {e}")
        print("Run 'python agent.py doctor' and check output/run.log.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
