#!/usr/bin/env python3
"""Localhost web UI for JobHunt. Stdlib only, no extra dependencies.

Usage:
    python ui.py [--port 8765]
    python agent.py ui [--port 8765]

Opens http://127.0.0.1:8765 in your browser. The page lets you paste a job
URL, watch progress live, download the tailored PDF, trigger Gmail checks,
and see health + tracked jobs. Long jobs run in background threads; the
browser polls for updates. Binds to localhost only; API keys never leave
the server (frontend receives masked status only).
"""
from __future__ import annotations

import contextlib
import io
import json
import mimetypes
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn

ROOT = Path(__file__).resolve().parent
UI_HTML = ROOT / "ui.html"

# Bump when the frontend and backend must match. The page checks this on
# load and shows a restart banner instead of cryptic 404s from a stale server.
UI_VERSION = 2

_tasks: dict[str, dict] = {}
_tasks_lock = threading.Lock()
_task_counter = [0]


# ---------------- pure logic (unit-testable, no HTTP) ----------------

def safe_output_path(rel: str) -> Path | None:
    """Resolve rel under output/; return None on escape attempts."""
    from src.utils import OUTPUT_ROOT
    try:
        base = OUTPUT_ROOT.resolve()
        p = (base / rel).resolve()
    except Exception:
        return None
    if p == base or base not in p.parents:
        return None
    return p if p.exists() else None


def list_jobs() -> list[dict]:
    """Tracked applications derived from output/*/job.json (+match.json)."""
    from src.utils import OUTPUT_ROOT
    jobs: list[dict] = []
    if not OUTPUT_ROOT.exists():
        return jobs
    for d in sorted(OUTPUT_ROOT.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not d.is_dir():
            continue
        jf = d / "job.json"
        if not jf.exists():
            continue
        try:
            job = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue
        match: dict = {}
        try:
            match = json.loads((d / "match.json").read_text(encoding="utf-8"))
        except Exception:
            pass
        pdfs = sorted(d.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
        jobs.append({
            "dir": d.name,
            "company": job.get("company", "?"),
            "title": job.get("title", "?"),
            "match_score": match.get("match_score"),
            "matching_skills": (match.get("matching_skills") or [])[:6],
            "missing_skills": (match.get("missing_skills") or [])[:6],
            "apply_link": job.get("apply_link", ""),
            "pdf_url": f"/output/{d.name}/{pdfs[0].name}" if pdfs else "",
            "updated": d.stat().st_mtime,
        })
    return jobs


def doctor_status() -> list[dict]:
    from src.doctor import run_doctor
    return [{"name": r.name, "ok": r.ok, "detail": r.detail, "fix": r.fix}
            for r in run_doctor()]


def get_sheet_url() -> str:
    """Public spreadsheet URL from config. Empty when not configured.

    Only the sheet URL leaves the server; no keys are ever exposed.
    """
    try:
        from src.config import load_config
        cfg = load_config(auto_wizard=False, demo=False)
    except Exception:
        return ""
    sid = (cfg.google_sheet_id or "").strip()
    if not sid or sid == "demo":
        return ""
    return f"https://docs.google.com/spreadsheets/d/{sid}"


def _new_task(kind: str) -> tuple[str, dict]:
    with _tasks_lock:
        _task_counter[0] += 1
        tid = f"{kind}-{_task_counter[0]}"
        task = {"id": tid, "kind": kind, "status": "running", "log": [], "result": {}}
        _tasks[tid] = task
    return tid, task


def get_task(tid: str) -> dict | None:
    with _tasks_lock:
        t = _tasks.get(tid)
        return dict(t, log=list(t["log"])) if t else None


class _LogWriter(io.TextIOBase):
    def __init__(self, task: dict):
        self.task = task
        self._buf = ""

    def write(self, s):
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.strip()
            if line:
                with _tasks_lock:
                    self.task["log"].append(line[-500:])
        return len(s)


def _finish_apply(task: dict, url: str, resume: bool, demo: bool = False) -> None:
    from src.pipeline import run_apply
    from src.job_api import parse_job_id
    code = run_apply(url, demo=demo, resume=resume)
    # Re-read artifacts for the result card (pipeline prints but returns only a code).
    try:
        jid = parse_job_id(url)
        match_dir = next((j for j in list_jobs() if j["dir"].endswith(f"_{jid}")), None)
    except Exception:
        match_dir = None
    task["result"] = {"exit_code": code, "job": match_dir}


def _finish_check_mail(task: dict, days: int, demo: bool = False) -> None:
    from src.pipeline import run_check_mail_flow
    code = run_check_mail_flow(days=days, demo=demo)
    task["result"] = {"exit_code": code}


def _spawn(kind: str, fn) -> str:
    tid, task = _new_task(kind)

    def _run():
        with contextlib.redirect_stdout(_LogWriter(task)):
            try:
                fn(task)
                with _tasks_lock:
                    task["status"] = "done"
            except Exception as e:  # noqa: BLE001 - surfaced to UI
                import traceback
                with _tasks_lock:
                    task["result"] = {"error": f"{type(e).__name__}: {e}",
                                      "trace": traceback.format_exc().strip().splitlines()[-8:]}
                    task["status"] = "error"
    threading.Thread(target=_run, daemon=True).start()
    return tid


def start_apply_task(url: str, resume: bool = False, demo: bool = False) -> str:
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("Please paste a full job URL starting with http(s)://")
    return _spawn("apply", lambda task: _finish_apply(task, url, resume, demo))


def start_check_mail_task(days: int = 14, demo: bool = False) -> str:
    return _spawn("check-mail", lambda task: _finish_check_mail(task, int(days), demo))


def start_doctor_task() -> str:
    from src.doctor import print_doctor, run_doctor
    return _spawn("doctor", lambda task: print_doctor(run_doctor()))


# ---------------- web console (allowlisted commands, never a shell) ----------------

CONSOLE_HELP = (
    "Allowed commands (this console never runs a shell):\n"
    "  doctor                      health check\n"
    "  check-mail [--days N] [--demo]   scan Gmail, update sheet\n"
    "  apply <url> [--resume] [--demo]  prepare one application\n"
    "  setup                       needs a real terminal (see below)\n"
    "  help                        this text\n"
)


def console_dispatch(command: str) -> dict:
    """Returns {"task_id": ...} for background jobs, {"output": ...} for
    instant answers, or {"error": ...} for disallowed input."""
    import shlex
    try:
        tokens = shlex.split(command or "", posix=False)
    except ValueError as e:
        return {"error": f"Could not parse command: {e}"}
    # unquote pasted "..." URLs (posix=False keeps the quotes)
    fixed = []
    for t in tokens:
        if len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"'):
            t = t[1:-1]
        fixed.append(t)
    tokens = fixed
    # tolerate a pasted "python agent.py ..." prefix
    while len(tokens) >= 2 and tokens[0] == "python" and tokens[1] == "agent.py":
        tokens = tokens[2:]
    if tokens and tokens[0] == "agent.py":
        tokens = tokens[1:]
    if not tokens or tokens[0] in ("help", "--help", "-h"):
        from src.cli import build_parser
        return {"output": build_parser().format_help() + "\n" + CONSOLE_HELP}
    if tokens[0] == "setup":
        return {"output": ("'setup' is interactive (it asks for keys) and needs a real "
                           "terminal.\nRun this in PowerShell:\n\n    python agent.py setup\n")}
    if tokens[0] == "doctor":
        if len(tokens) > 1:
            return {"error": "'doctor' takes no arguments. Try: doctor"}
        return {"task_id": start_doctor_task()}
    if tokens[0] == "check-mail":
        days, demo = 14, False
        rest = tokens[1:]
        if "--demo" in rest or "--mock" in rest:
            demo = True
        if "--days" in rest:
            try:
                days = int(rest[rest.index("--days") + 1])
            except (ValueError, IndexError):
                return {"error": "Usage: check-mail [--days N] [--demo]"}
        return {"task_id": start_check_mail_task(days, demo)}
    if tokens[0] == "apply":
        from src.cli import normalize_args
        try:
            ns = normalize_args(tokens)
        except SystemExit:
            return {"error": "Usage: apply <job-url> [--resume] [--demo]"}
        if ns.command != "apply" or not getattr(ns, "url", None):
            return {"error": "Usage: apply <job-url> [--resume] [--demo]"}
        try:
            tid = start_apply_task(ns.url, resume=bool(getattr(ns, "resume", False)),
                                   demo=bool(getattr(ns, "demo", False)))
        except ValueError as e:
            return {"error": str(e)}
        return {"task_id": tid}
    return {"error": f"Not allowed here: '{tokens[0]}'. {CONSOLE_HELP}"}


# ---------------- HTTP layer ----------------

class Handler(BaseHTTPRequestHandler):
    server_version = "JobHuntUI/1.0"

    def log_message(self, *a):  # keep console clean
        pass

    def _json(self, obj, code: int = 200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            n = 0
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path in ("/", "/index.html"):
                data = UI_HTML.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            elif path == "/api/doctor":
                self._json({"checks": doctor_status()})
            elif path == "/api/jobs":
                self._json({"jobs": list_jobs()})
            elif path == "/api/sheet":
                self._json({"sheet_url": get_sheet_url()})
            elif path == "/api/version":
                self._json({"version": UI_VERSION})
            elif path.startswith("/api/tasks/"):
                task = get_task(path.rsplit("/", 1)[-1])
                self._json(task or {"error": "unknown task"}, 200 if task else 404)
            elif path.startswith("/output/"):
                rel = urllib.parse.unquote(path[len("/output/"):])
                p = safe_output_path(rel)
                if p is None or p.is_dir():
                    self._json({"error": "not found"}, 404)
                    return
                data = p.read_bytes()
                ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                if p.suffix.lower() == ".pdf":
                    self.send_header("Content-Disposition", f'inline; filename="{p.name}"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self._json({"error": "not found"}, 404)
        except BrokenPipeError:
            pass
        except Exception as e:  # noqa: BLE001 - API must never crash
            try:
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)
            except Exception:
                pass

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/apply":
                body = self._read_json()
                try:
                    tid = start_apply_task(body.get("url", ""), bool(body.get("resume")))
                except ValueError as e:
                    self._json({"error": str(e)}, 400)
                    return
                self._json({"task_id": tid})
            elif parsed.path == "/api/check-mail":
                body = self._read_json()
                try:
                    days = int(body.get("days", 14))
                except (TypeError, ValueError):
                    days = 14
                self._json({"task_id": start_check_mail_task(days)})
            elif parsed.path == "/api/console":
                body = self._read_json()
                res = console_dispatch(body.get("command", ""))
                self._json(res, 200 if "error" not in res else 400)
            else:
                self._json({"error": "not found"}, 404)
        except BrokenPipeError:
            pass
        except Exception as e:  # noqa: BLE001 - API must never crash
            try:
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)
            except Exception:
                pass


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def main(port: int = 8765, open_browser: bool = True) -> None:
    server = ThreadedHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"JobHunt UI running at {url} (localhost only, Ctrl+C to stop)")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    import sys
    _port = 8765
    for _i, _a in enumerate(sys.argv[1:]):
        if _a == "--port" and _i + 1 < len(sys.argv[1:]):
            _port = int(sys.argv[1:][_i + 1])
    main(_port)
