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

# Bump on EVERY ui.py/ui.html change. The page checks this on load and
# shows a restart banner instead of cryptic 404s from a stale server.
# (test_ui.py::test_frontend_backend_version_sync enforces the match.)
UI_VERSION = 7

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


def _tombstone_path() -> Path:
    from src.utils import OUTPUT_ROOT
    return OUTPUT_ROOT / ".deleted.json"


def load_tombstones() -> set[str]:
    """Dirs the user soft-deleted (hidden, restorable, never erased)."""
    try:
        data = json.loads(_tombstone_path().read_text(encoding="utf-8"))
        return set(data.get("deleted", [])) if isinstance(data, dict) else set()
    except Exception:
        return set()


def _save_tombstones(names: set[str]) -> None:
    from src.utils import OUTPUT_ROOT
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    # prune entries whose folders are gone entirely
    names = {n for n in names if (OUTPUT_ROOT / n).exists()}
    _tombstone_path().write_text(json.dumps({"deleted": sorted(names)}), encoding="utf-8")


def soft_delete_job(job_dir_name: str) -> dict:
    d = _job_dir(job_dir_name)
    if d is None:
        raise ValueError("Unknown job folder.")
    tomb = load_tombstones()
    tomb.add(d.name)
    _save_tombstones(tomb)
    return {"ok": True, "dir": d.name, "deleted": True}


def restore_job(job_dir_name: str) -> dict:
    name = (job_dir_name or "").strip()
    if not name or "/" in name or "\\" in name:
        raise ValueError("Unknown job folder.")
    tomb = load_tombstones()
    tomb.discard(name)
    _save_tombstones(tomb)
    return {"ok": True, "dir": name, "deleted": False}


def list_jobs(include_deleted: bool = False) -> list[dict]:
    """Tracked applications derived from output/*/job.json (+match.json).

    Soft-deleted folders are hidden unless include_deleted=True (flagged).
    """
    from src.utils import OUTPUT_ROOT
    jobs: list[dict] = []
    if not OUTPUT_ROOT.exists():
        return jobs
    tomb = load_tombstones()
    for d in sorted(OUTPUT_ROOT.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not d.is_dir():
            continue
        deleted = d.name in tomb
        if deleted and not include_deleted:
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
            "deleted": deleted,
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


MAX_TEX_BYTES = 500_000


def _job_dir(name: str) -> Path | None:
    """Validate a job folder name: direct child of output/ containing a resume."""
    if not name or "/" in name or "\\" in name:
        return None
    d = safe_output_path(name)
    if d is None or not d.is_dir():
        return None
    return d


def find_resume_tex(job_dir: Path) -> Path | None:
    """Newest *Resume*.tex in the folder (covers old + dated naming)."""
    cands = sorted(job_dir.glob("*Resume*.tex"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0] if cands else None


def get_tex(job_dir_name: str) -> dict:
    d = _job_dir(job_dir_name)
    if d is None:
        raise ValueError("Unknown job folder.")
    tex = find_resume_tex(d)
    if tex is None:
        raise ValueError("No resume .tex in that folder yet — run an application first.")
    return {"dir": d.name, "file": tex.name, "content": tex.read_text(encoding="utf-8")}


def _honesty_warnings(job_dir: Path, content: str) -> list[str]:
    """Skills the edited resume claims without base/profile evidence.

    Vocabulary comes from the run's match.json; never fails (returns []).
    Display-only: saves always go through.
    """
    try:
        from src.verify import find_unverified_claims
        from src.utils import PROJECT_ROOT
        m = json.loads((job_dir / "match.json").read_text(encoding="utf-8"))
        vocab = (m.get("matching_skills", []) + m.get("missing_skills", [])
                 + m.get("core_requirements", []) + m.get("profile_skills", []))
        base = (PROJECT_ROOT / "main.tex").read_text(encoding="utf-8")
        if not base.strip():
            return []
        prof = ""
        try:
            from src.profile import get_candidate_context
            prof = get_candidate_context().text
        except Exception:
            pass
        return find_unverified_claims(content, [base] + ([prof] if prof else []), vocab)[:10]
    except Exception:
        return []


def save_tex(job_dir_name: str, content: str, compile_pdf: bool = True) -> dict:
    d = _job_dir(job_dir_name)
    if d is None:
        raise ValueError("Unknown job folder.")
    if not content or not content.strip():
        raise ValueError("Refusing to save an empty resume.")
    if len(content.encode("utf-8")) > MAX_TEX_BYTES:
        raise ValueError("Resume too large (500 KB limit).")
    tex = find_resume_tex(d)
    if tex is None:
        # Fresh resume file in this folder (uses current naming convention).
        from src.tailor import resume_stem
        try:
            from src.config import load_config
            applicant = load_config(auto_wizard=False, demo=True).applicant_name
        except Exception:
            applicant = "Chaitanya Jain"
        parts = d.name.rsplit("_", 1)
        company = parts[0] if len(parts) == 2 else d.name
        tex = d / f"{resume_stem(company, applicant)}.tex"
    tex.write_text(content, encoding="utf-8")
    warnings = _honesty_warnings(d, content)
    if not compile_pdf:
        return {"ok": True, "file": tex.name, "compiled": False, "warnings": warnings}
    from src.compiler import LatexCompileError, compile_tex
    try:
        pdf = compile_tex(tex)
        return {"ok": True, "file": tex.name, "compiled": True,
                "pdf_url": f"/output/{d.name}/{pdf.name}", "warnings": warnings}
    except LatexCompileError as e:
        log = (e.log or str(e))[-3000:]
        return {"ok": False, "file": tex.name, "compiled": False,
                "error": str(e)[:500], "compile_log": log}


JOB_ID_RE = None  # compiled lazily (see _job_id_re)


def _job_id_re():
    global JOB_ID_RE
    if JOB_ID_RE is None:
        import re
        JOB_ID_RE = re.compile(r"^[A-Za-z0-9_+/=-]{32,}$")
    return JOB_ID_RE


def looks_like_job_id(s: str) -> bool:
    return bool(_job_id_re().match((s or "").strip()))


def search_jobs_api(query: str, country: str = "") -> list[dict]:
    """Keyword search via JSearch; light normalized results for the UI."""
    import re
    from src.config import ConfigError, load_config
    from src import job_api
    query = (query or "").strip()
    if not query:
        raise ValueError("Type keywords to search (e.g. data engineer).")
    try:
        cfg = load_config(auto_wizard=False, demo=False)
    except ConfigError as e:
        raise ValueError(str(e))
    try:
        items = job_api.search_jobs(query, cfg.rapidapi_key, cfg.rapidapi_host,
                                    cfg.rapidapi_search_endpoint,
                                    (country or cfg.rapidapi_country or "in"))
    except Exception as e:  # noqa: BLE001 - surfaced to UI
        raise ValueError(f"Job search failed: {e}")
    out = []
    for it in items[:10]:
        jid = job_api._pick(it, "job_id", "id")
        if not jid:
            continue
        title = job_api._pick(it, "job_title", "title", default="Untitled")
        company = job_api._pick(it, "employer_name", "company_name", "company", default="?")
        desc = re.sub(r"\s+", " ", job_api._pick(it, "job_description", "description")).strip()
        link, direct = _linkedin_url(it, title, company)
        out.append({
            "job_id": jid,
            "title": title,
            "company": company,
            "location": job_api._pick(it, "job_location", "job_city", default=""),
            "posted": job_api._pick(it, "job_posted_at", default=""),
            "snippet": desc[:300],
            "salary": job_api._pick(it, "job_salary_string", "job_salary", default=""),
            "linkedin_url": link,
            "linkedin_direct": direct,
        })
    return out


def _linkedin_url(item: dict, title: str, company: str) -> tuple[str, bool]:
    """(url, is_direct_posting). Prefers a real linkedin.com/jobs/view link
    from the result's apply options; otherwise a LinkedIn keyword search."""
    links: list[str] = []
    for key in ("job_apply_link", "job_google_link"):
        v = item.get(key)
        if isinstance(v, str) and v.strip():
            links.append(v.strip())
    for opt in item.get("apply_options", []) or []:
        if isinstance(opt, dict):
            for key in ("apply_link", "link", "url"):
                v = opt.get(key)
                if isinstance(v, str) and v.strip():
                    links.append(v.strip())
    for link in links:
        if "linkedin.com/jobs/view" in link:
            return link, True
    q = urllib.parse.quote_plus(f"{title} {company}".strip() or title)
    return f"https://www.linkedin.com/jobs/search/?keywords={q}", False


def base_tex_path() -> Path | None:
    """Absolute path of main.tex, or None when the user hasn't added one."""
    from src.utils import PROJECT_ROOT
    p = PROJECT_ROOT / "main.tex"
    return p if p.is_file() else None


def get_base_tex() -> dict:
    p = base_tex_path()
    if p is None:
        raise ValueError("No main.tex in the project folder yet — add your base resume first.")
    return {"file": "main.tex", "content": p.read_text(encoding="utf-8")}


def save_base_tex(content: str) -> dict:
    p = base_tex_path()
    if p is None:
        raise ValueError("No main.tex in the project folder yet — add your base resume first.")
    if not content or not content.strip():
        raise ValueError("Refusing to save an empty resume.")
    if len(content.encode("utf-8")) > MAX_TEX_BYTES:
        raise ValueError("Resume too large (500 KB limit).")
    if "\\documentclass" not in content or "\\begin{document}" not in content:
        raise ValueError("Doesn't look like a LaTeX resume (missing documentclass/begin).")
    bak = p.parent / "main.tex.bak"
    try:
        bak.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception:
        pass
    p.write_text(content, encoding="utf-8")
    return {"ok": True, "file": "main.tex", "backup": "main.tex.bak"}


def parse_tex_content(content: str) -> dict:
    from src.resume_model import parse_resume
    try:
        return parse_resume(content).to_dict()
    except ValueError as e:
        raise ValueError(str(e))


def build_tex_content(head: str, sections: list, tail: str) -> str:
    from src.resume_model import Section, build_resume
    if not isinstance(sections, list) or not sections:
        raise ValueError("No sections to build from.")
    try:
        return build_resume(head, [Section.from_dict(s) for s in sections], tail or "")
    except ValueError as e:
        raise ValueError(str(e))


def render_preview(content: str) -> dict:
    """Compile content to a throwaway PDF for preview. Never touches real files."""
    if not content or not content.strip():
        raise ValueError("Nothing to preview.")
    if len(content.encode("utf-8")) > MAX_TEX_BYTES:
        raise ValueError("Resume too large (500 KB limit).")
    from src.compiler import LatexCompileError, compile_tex
    from src.utils import OUTPUT_ROOT
    prev = OUTPUT_ROOT / ".preview"
    prev.mkdir(parents=True, exist_ok=True)
    tex = prev / "preview.tex"
    tex.write_text(content, encoding="utf-8")
    try:
        pdf = compile_tex(tex)
        return {"ok": True, "pdf_url": f"/output/.preview/{pdf.name}"}
    except LatexCompileError as e:
        return {"ok": False, "error": str(e)[:500],
                "compile_log": (e.log or str(e))[-3000:]}


def profile_status() -> dict:
    """LinkedIn supplement state for the UI. Never raises, never leaks keys."""
    try:
        from src.config import load_config
        from src.profile import get_candidate_context
        cfg = load_config(auto_wizard=False, demo=False)
        prof = get_candidate_context(cfg.linkedin_profile_url, cfg.linkedin_profile_file)
    except Exception:
        return {"source": "none", "skills": [], "total": 0}
    return {"source": prof.source, "skills": prof.skills[:12], "total": len(prof.skills)}


MAX_PROFILE_BYTES = 100_000


def _profile_file_path() -> Path:
    from src.utils import PROJECT_ROOT
    try:
        from src.config import load_config
        name = load_config(auto_wizard=False, demo=True).linkedin_profile_file or "profile.md"
    except Exception:
        name = "profile.md"
    p = Path(name)
    return p if p.is_absolute() else PROJECT_ROOT / name


def get_profile_file() -> dict:
    p = _profile_file_path()
    try:
        content = p.read_text(encoding="utf-8")
    except Exception:
        content = ""
    return {"file": p.name, "exists": bool(content), "content": content}


def get_profile_template() -> dict:
    from src.utils import PROJECT_ROOT
    ex = PROJECT_ROOT / "profile.md.example"
    try:
        return {"content": ex.read_text(encoding="utf-8")}
    except Exception:
        raise ValueError("profile.md.example not found.")


def save_profile_file(content: str) -> dict:
    from src.profile import load_local_profile
    if not content or not content.strip():
        raise ValueError("Refusing to save an empty profile (delete the file to opt out).")
    if len(content.encode("utf-8")) > MAX_PROFILE_BYTES:
        raise ValueError("Profile too large (100 KB limit).")
    p = _profile_file_path()
    p.write_text(content, encoding="utf-8")
    _, skills = load_local_profile(str(p))
    return {"ok": True, "file": p.name, "skills": skills}


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


def _resolve_job_dir(url_or_id: str, started: float) -> dict | None:
    """Find the result card data for a finished apply run.

    URL inputs match by job-ID suffix; JSearch-ID inputs (not URLs) match
    the freshest folder written after the run started.
    """
    from src.job_api import parse_job_id
    try:
        if url_or_id.startswith("http"):
            jid = parse_job_id(url_or_id)
            return next((j for j in list_jobs() if j["dir"].endswith(f"_{jid}")), None)
    except Exception:
        pass
    fresh = [j for j in list_jobs() if j.get("updated", 0) >= started - 5]
    return fresh[0] if fresh else None


def _persist_task_log(task: dict) -> None:
    """Append finished task logs so failures stay debuggable after reload."""
    try:
        from src.utils import OUTPUT_ROOT
        from datetime import datetime
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_ROOT / "ui_tasks.log", "a", encoding="utf-8") as f:
            f.write(f"\n=== {datetime.now().isoformat()} {task['id']} "
                    f"{task['status']} ===\n")
            f.write("\n".join(task["log"][-100:]) + "\n")
    except Exception:
        pass


def _finish_apply(task: dict, url: str, resume: bool, demo: bool = False) -> None:
    import time
    from src.pipeline import run_apply
    started = time.time()
    code = run_apply(url, demo=demo, resume=resume)
    # Re-read artifacts for the result card (pipeline prints but returns only a code).
    task["result"] = {"exit_code": code, "job": _resolve_job_dir(url, started)}


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
            finally:
                with _tasks_lock:
                    _persist_task_log(task)
    threading.Thread(target=_run, daemon=True).start()
    return tid


def start_apply_task(url: str = "", resume: bool = False, demo: bool = False,
                     job_id: str = "") -> str:
    url, job_id = (url or "").strip(), (job_id or "").strip()
    if job_id:
        if not looks_like_job_id(job_id):
            raise ValueError("That doesn't look like a JSearch job ID.")
        target = job_id
    elif url.startswith(("http://", "https://")):
        target = url
    else:
        raise ValueError("Please paste a full job URL starting with http(s)://")
    return _spawn("apply", lambda task: _finish_apply(task, target, resume, demo))


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
        u = ns.url.strip()
        kw = {"resume": bool(getattr(ns, "resume", False)),
              "demo": bool(getattr(ns, "demo", False))}
        try:
            if u.startswith(("http://", "https://")):
                tid = start_apply_task(u, **kw)
            elif looks_like_job_id(u):
                tid = start_apply_task(job_id=u, demo=kw["demo"])
            else:
                return {"error": "Usage: apply <job-url> [--resume] [--demo]"}
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
                qs = urllib.parse.parse_qs(parsed.query)
                inc = qs.get("include_deleted", [""])[0] in ("1", "true", "yes")
                self._json({"jobs": list_jobs(include_deleted=inc)})
            elif path == "/api/sheet":
                self._json({"sheet_url": get_sheet_url()})
            elif path == "/api/profile":
                self._json(profile_status())
            elif path == "/api/profile-file":
                self._json(get_profile_file())
            elif path == "/api/profile-template":
                try:
                    self._json(get_profile_template())
                except ValueError as e:
                    self._json({"error": str(e)}, 400)
            elif path == "/api/version":
                self._json({"version": UI_VERSION})
            elif path == "/api/base":
                try:
                    self._json(get_base_tex())
                except ValueError as e:
                    self._json({"error": str(e)}, 400)

            elif path == "/api/tex":
                qs = urllib.parse.parse_qs(parsed.query)
                try:
                    self._json(get_tex(qs.get("dir", [""])[0]))
                except ValueError as e:
                    self._json({"error": str(e)}, 400)
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
                    tid = start_apply_task(body.get("url", ""), bool(body.get("resume")),
                                           job_id=body.get("job_id", ""))
                except ValueError as e:
                    self._json({"error": str(e)}, 400)
                    return
                self._json({"task_id": tid})
            elif parsed.path == "/api/search":
                body = self._read_json()
                try:
                    jobs = search_jobs_api(body.get("query", ""), body.get("country", ""))
                except ValueError as e:
                    self._json({"error": str(e)}, 400)
                    return
                self._json({"jobs": jobs})
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
            elif parsed.path == "/api/jobs/delete":
                body = self._read_json()
                try:
                    self._json(soft_delete_job(body.get("dir", "")))
                except ValueError as e:
                    self._json({"error": str(e)}, 400)
            elif parsed.path == "/api/jobs/restore":
                body = self._read_json()
                try:
                    self._json(restore_job(body.get("dir", "")))
                except ValueError as e:
                    self._json({"error": str(e)}, 400)
            elif parsed.path == "/api/tex":
                body = self._read_json()
                try:
                    res = save_tex(body.get("dir", ""), body.get("content", ""),
                                   bool(body.get("compile", True)))
                except ValueError as e:
                    self._json({"error": str(e)}, 400)
                    return
                self._json(res, 200 if res.get("ok") else 422)
            elif parsed.path == "/api/base":
                body = self._read_json()
                try:
                    self._json(save_base_tex(body.get("content", "")))
                except ValueError as e:
                    self._json({"error": str(e)}, 400)
            elif parsed.path == "/api/profile-file":
                body = self._read_json()
                try:
                    self._json(save_profile_file(body.get("content", "")))
                except ValueError as e:
                    self._json({"error": str(e)}, 400)
            elif parsed.path == "/api/parse":
                # {content} for raw text, or {source:"base"} / {source:"job",dir}
                body = self._read_json()
                try:
                    if body.get("content"):
                        content = body["content"]
                    elif body.get("source") == "base":
                        content = get_base_tex()["content"]
                    else:
                        d = _job_dir(body.get("dir", ""))
                        if d is None:
                            raise ValueError("Unknown job folder.")
                        tex = find_resume_tex(d)
                        if tex is None:
                            raise ValueError("No resume .tex in that folder yet.")
                        content = tex.read_text(encoding="utf-8")
                    self._json(parse_tex_content(content))
                except ValueError as e:
                    self._json({"error": str(e)}, 400)
            elif parsed.path == "/api/build":
                body = self._read_json()
                try:
                    content = build_tex_content(body.get("head", ""),
                                                body.get("sections", []),
                                                body.get("tail", ""))
                except ValueError as e:
                    self._json({"error": str(e)}, 400)
                    return
                self._json({"content": content})
            elif parsed.path == "/api/preview":
                body = self._read_json()
                try:
                    res = render_preview(body.get("content", ""))
                except ValueError as e:
                    self._json({"error": str(e)}, 400)
                    return
                self._json(res, 200 if res.get("ok") else 422)
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
