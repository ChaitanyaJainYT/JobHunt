"""doctor: single health-check command. No tracebacks, PASS/FAIL table."""
from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from src.config import ENV_PATH, _read_dotenv
from src.utils import PROJECT_ROOT


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    fix: str = ""


def run_doctor() -> list[CheckResult]:
    results: list[CheckResult] = []

    # 1. Python version
    ok = sys.version_info >= (3, 10)
    results.append(CheckResult(
        "Python >= 3.10", ok,
        f"{sys.version.split()[0]}",
        "" if ok else "Install Python 3.10+ from https://www.python.org/downloads/",
    ))

    # 2. tectonic (bundled copy counts: no PATH setup needed)
    from src.compiler import bundled_tectonic, tectonic_install_hint
    bundled = bundled_tectonic()
    found = str(bundled) if bundled is not None else shutil.which("tectonic")
    results.append(CheckResult(
        "tectonic available", bool(found),
        f"{found} (bundled)" if bundled is not None else (found or "not found"),
        "" if found else tectonic_install_hint(),
    ))

    # 3. base resume
    main = PROJECT_ROOT / "main.tex"
    sample = PROJECT_ROOT / "main.tex.sample"
    ok = main.exists() or sample.exists()
    results.append(CheckResult(
        "Base resume", ok,
        str(main if main.exists() else sample if sample.exists() else "missing main.tex"),
        "" if ok else "Place your Overleaf resume as main.tex in project root.",
    ))

    # 4. .env keys (presence only, masked)
    values = _read_dotenv(ENV_PATH) if ENV_PATH.exists() else {}
    import os
    for key in ["GEMINI_API_KEY", "RAPIDAPI_KEY", "GOOGLE_SHEET_ID"]:
        v = os.environ.get(key, values.get(key, ""))
        alt_ok = key == "GEMINI_API_KEY" and bool(os.environ.get("GROQ_API_KEY", values.get("GROQ_API_KEY", "")))
        ok = bool(v) or alt_ok
        results.append(CheckResult(
            f".env {key}", ok,
            "set (masked)" if ok else "missing",
            "" if ok else "Run: python agent.py setup  (or use --demo for offline trial).",
        ))

    # 5. Google credentials file
    cred_name = values.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    cred = PROJECT_ROOT / cred_name
    tok = PROJECT_ROOT / "token.json"
    ok = cred.exists() or tok.exists()
    results.append(CheckResult(
        "Google OAuth", ok,
        f"credentials={'yes' if cred.exists() else 'no'}, token={'yes' if tok.exists() else 'no'}",
        "" if ok else "Create Desktop-OAuth client in Google Cloud Console, download as credentials.json to project root.",
    ))

    # 6. dependencies importable
    try:
        import dotenv  # noqa: F401
        import requests  # noqa: F401
        results.append(CheckResult("Python deps", True, "dotenv+requests importable", ""))
    except Exception as e:
        results.append(CheckResult("Python deps", False, str(e), "Run: pip install -r requirements.txt"))

    return results


def print_doctor(results: list[CheckResult]) -> int:
    print("\n== JobHunt doctor ==\n")
    print(f"{'CHECK':28} {'STATUS':8} DETAIL")
    print("-" * 70)
    fails = 0
    for r in results:
        status = "PASS" if r.ok else "FAIL"
        if not r.ok:
            fails += 1
        print(f"{r.name:28} {status:8} {r.detail}")
        if not r.ok and r.fix:
            print(f"{'':28}  Fix: {r.fix}")
    print("-" * 70)
    if fails:
        print(f"{fails} check(s) failing. Tip: 'python agent.py setup' then re-run doctor. '--demo' bypasses keys.")
    else:
        print("All green. Try: python agent.py --demo \"https://www.linkedin.com/jobs/view/4012345678\"")
    return 1 if fails else 0
