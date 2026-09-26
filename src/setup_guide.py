"""Guided setup: single source of truth for CLI wizard + web Setup page.

Each SETUP_ITEM describes one thing the user must provide: what it is,
exact steps to get it (with a direct link), and a format-only validator
(no network calls, no quota spent). Comma-separated values are accepted
for key items (rotation-ready): every part is validated.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field


# ---------------- validators (pure, offline) ----------------

def _split_keys(value: str) -> list[str]:
    return [p.strip() for p in (value or "").split(",") if p.strip()]


def valid_gemini_key(value: str) -> str | None:
    """None if ok, else human-readable error."""
    parts = _split_keys(value)
    if not parts:
        return "Paste at least one key."
    for p in parts:
        if re.fullmatch(r"AIza[0-9A-Za-z\-_]{35}", p):
            continue
        # Other Google-issued key shapes exist (e.g. longer Cloud formats):
        # accept long opaque tokens, reject obvious typos/URLs.
        if len(p) >= 30 and re.fullmatch(r"[A-Za-z0-9\-_\.]+", p):
            continue
        return (f"Doesn't look like a Gemini key ({p[:8]}…): expected 'AIza…' + 35 chars, "
                "or another long Google-issued token.")
    return None


def valid_groq_key(value: str) -> str | None:
    parts = _split_keys(value)
    if not parts:
        return None  # optional when Gemini is set; requiredness handled by caller
    for p in parts:
        if not re.fullmatch(r"gsk_[A-Za-z0-9]{20,}", p):
            return f"Doesn't look like a Groq key ({p[:8]}…): expected 'gsk_… + 20 chars."
    return None


def valid_rapidapi_key(value: str) -> str | None:
    parts = _split_keys(value)
    if not parts:
        return "Paste at least one key."
    for p in parts:
        if len(p) < 20:
            return f"Too short to be a RapidAPI key ({p[:8]}…). Keys live under the API's Security tab."
    return None


def extract_sheet_id(value: str) -> str:
    """Accept a full Sheets URL or a bare ID. Returns '' when unparseable."""
    v = (value or "").strip()
    m = re.search(r"/d/([A-Za-z0-9-_]+)", v)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9-_]{20,}", v):
        return v
    return ""


def valid_sheet_id(value: str) -> str | None:
    if not extract_sheet_id(value):
        return "Paste the Sheet's URL (…/d/<id>/…) or the ID itself."
    return None


MAX_RESUME_BYTES = 500_000


def install_base_resume(content: str, project_root=None) -> dict:
    """Validate + save uploaded content as main.tex, backing up any existing.

    Returns {"file", "replaced": bool, "backup": str|None}.
    Raises ValueError on empty/oversize/non-LaTeX content.
    """
    from pathlib import Path as _P
    if project_root is None:
        from src.utils import PROJECT_ROOT as _PR
        project_root = _PR
    if not content or not content.strip():
        raise ValueError("Empty file — nothing to install.")
    if len(content.encode("utf-8")) > MAX_RESUME_BYTES:
        raise ValueError("File too large (500 KB limit).")
    if "\\documentclass" not in content or "\\begin{document}" not in content:
        raise ValueError("Doesn't look like a LaTeX resume (missing documentclass/begin).")
    root = _P(str(project_root))
    dst = root / "main.tex"
    replaced = dst.is_file()
    backup = None
    if replaced:
        backup = "main.tex.bak"
        (root / backup).write_text(dst.read_text(encoding="utf-8"), encoding="utf-8")
    dst.write_text(content, encoding="utf-8")
    return {"file": "main.tex", "replaced": replaced, "backup": backup}


def check_credentials_file(path) -> str | None:
    """None if a Desktop OAuth client file, else error. Never reads secrets."""
    from pathlib import Path as _P
    p = _P(str(path))
    if not p.is_file():
        return f"Not found at {p}. Download it (steps above) and place it there."
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return "Not valid JSON — re-download from Google Cloud Console."
    installed = data.get("installed") or {}
    if not installed.get("client_id"):
        return "Not a Desktop OAuth client file (missing installed.client_id)."
    return None


# ---------------- item table ----------------

@dataclass
class SetupItem:
    key: str              # .env key, or pseudo-key for files
    title: str
    why: str
    steps: list[str] = field(default_factory=list)
    open_url: str = ""
    open_label: str = ""
    optional: bool = False
    kind: str = "env"     # "env" | "file"
    default: str = ""     # offered on Enter when blank (env items)


SETUP_ITEMS: list[SetupItem] = [
    SetupItem(
        key="GEMINI_API_KEY", title="Gemini API key",
        why="Powers skill matching, resume tailoring, and email classification.",
        steps=[
            "Open the Google AI Studio key page (button below).",
            "Click “Get API Key”, then “Create API key”.",
            "Copy the key (usually starting with AIza…; you can add more later, comma-separated).",
        ],
        open_url="https://aistudio.google.com/app/apikey",
        open_label="Get Gemini key",
    ),
    SetupItem(
        key="GROQ_API_KEY", title="Groq API key (backup LLM)", optional=True,
        why="Free fallback used automatically when Gemini hits quota.",
        steps=[
            "Open the Groq console keys page (button below) and sign in.",
            "Click “Create API Key”.",
            "Copy it immediately — Groq shows the secret only once.",
        ],
        open_url="https://console.groq.com/keys",
        open_label="Get Groq key",
    ),
    SetupItem(
        key="RAPIDAPI_KEY", title="RapidAPI key (JSearch)",
        why="Fetches structured job data for LinkedIn URLs.",
        steps=[
            "Open the JSearch API page (button below).",
            "Pick a plan on the Pricing tab and Subscribe (free tier exists).",
            "Your key is under the API's Security tab — paste it here (comma-separated for rotation).",
        ],
        open_url="https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch",
        open_label="Subscribe to JSearch free",
    ),
    SetupItem(
        key="GOOGLE_SHEET_ID", title="Google Sheet tracker",
        why="Where applications get logged and statuses updated.",
        steps=[
            "Create a blank sheet (button below).",
            "Paste its full URL here — the ID is extracted automatically.",
        ],
        open_url="https://sheets.google.com",
        open_label="New Google Sheet",
    ),
    SetupItem(
        key="credentials.json", title="Google OAuth client file", kind="file",
        why="Lets the app log to your Sheet and read Gmail (one consent click).",
        steps=[
            "Open Google Cloud credentials (button below), create/select a project.",
            "Enable the Google Sheets API and Gmail API (Library tab).",
            "OAuth consent screen → External → add your Gmail as a test user.",
            "Clients → Create Client → Desktop app → Download JSON.",
            "Save the download as credentials.json in the project folder.",
        ],
        open_url="https://console.cloud.google.com/apis/credentials",
        open_label="Google Cloud credentials",
    ),
    SetupItem(
        key="APPLICANT_NAME", title="Your name",
        why="Used in tailored resume filenames: <COMPANY>_<Name>_Resume_<DDMMYY>.pdf.",
        steps=[],
        default="Chaitanya Jain",
    ),
    SetupItem(
        key="main.tex", title="Base resume file", kind="file",
        why="Your master resume; tailored copies are generated from it (never modified).",
        steps=["Place your LaTeX resume as main.tex in the project folder."],
    ),
    SetupItem(
        key="profile.md", title="LinkedIn profile supplement", kind="file", optional=True,
        why="Extra skills evidence merged into matching (see LinkedIn panel in the UI).",
        steps=["Copy profile.md.example to profile.md and paste your About + Skills."],
    ),
]

_VALIDATORS = {
    "GEMINI_API_KEY": valid_gemini_key,
    "GROQ_API_KEY": valid_groq_key,
    "RAPIDAPI_KEY": valid_rapidapi_key,
    "GOOGLE_SHEET_ID": valid_sheet_id,
    "APPLICANT_NAME": lambda v: None if v.strip() else "Name can't be blank.",
}


def validate_item(item: SetupItem, value: str):
    """(ok, message). File items are checked live against disk elsewhere."""
    if item.kind != "env":
        return True, ""
    if not (value or "").strip() and item.optional:
        return True, "skipped (optional)"
    fn = _VALIDATORS.get(item.key, lambda v: None if v.strip() else "Can't be blank.")
    err = fn(value or "")
    return (False, err) if err else (True, "ok")


def get_setup_state() -> list[dict]:
    """Status per item for the web UI. Never includes secret values."""
    from src import config as C
    values = C._read_dotenv(C.ENV_PATH) if C.ENV_PATH.exists() else {}
    from src.utils import PROJECT_ROOT
    out = []
    for it in SETUP_ITEMS:
        if it.kind == "env":
            v = os.environ.get(it.key, values.get(it.key, "")).strip()
            if it.key == "GOOGLE_SHEET_ID" and v:
                v = extract_sheet_id(v) or v
            if not v:
                if it.optional:
                    status, detail = "skipped", "optional — skipped"
                else:
                    status, detail = "missing", "not set"
            else:
                ok, msg = validate_item(it, v)
                if it.key in ("GEMINI_API_KEY", "GROQ_API_KEY", "RAPIDAPI_KEY"):
                    n = len(_split_keys(v))
                    detail = f"{n} key{'s' if n != 1 else ''} set (masked)" if ok else msg
                else:
                    detail = "set (masked)" if ok else msg
                status = "ready" if ok else "invalid"
            out.append({"key": it.key, "title": it.title, "why": it.why,
                        "steps": it.steps, "open_url": it.open_url,
                        "open_label": it.open_label, "optional": it.optional,
                        "kind": "env", "status": status, "detail": detail})
        else:
            if it.key == "credentials.json":
                err = check_credentials_file(PROJECT_ROOT / "credentials.json")
                status = "ready" if not err else "missing"
                detail = "Desktop client found" if not err else (err or "")
            elif it.key == "main.tex":
                ok = (PROJECT_ROOT / "main.tex").is_file()
                status = "ready" if ok else "missing"
                detail = "main.tex found" if ok else "place main.tex in project folder"
            else:  # profile.md
                ok = (PROJECT_ROOT / "profile.md").is_file()
                status = "ready" if ok else "skipped"
                detail = "profile.md found" if ok else "optional — copy from profile.md.example"
            out.append({"key": it.key, "title": it.title, "why": it.why,
                        "steps": it.steps, "open_url": it.open_url,
                        "open_label": it.open_label, "optional": it.optional,
                        "kind": "file", "status": status, "detail": detail})
    return out


def save_setup_value(key: str, value: str) -> dict:
    """Validate + persist one .env value. Rejects unknown keys and file items."""
    from src import config as C
    item = next((i for i in SETUP_ITEMS if i.key == key and i.kind == "env"), None)
    if item is None:
        raise ValueError(f"Unknown setting: {key}")
    v = (value or "").strip()
    if key == "GOOGLE_SHEET_ID":
        extracted = extract_sheet_id(v)
        if not extracted:
            raise ValueError(validate_item(item, v)[1])
        v = extracted
    else:
        ok, msg = validate_item(item, v)
        if not ok:
            raise ValueError(msg)
    values = C._read_dotenv(C.ENV_PATH) if C.ENV_PATH.exists() else {}
    values[key] = v
    C._write_dotenv(C.ENV_PATH, values)
    n = len(_split_keys(v)) if key in ("GEMINI_API_KEY", "GROQ_API_KEY", "RAPIDAPI_KEY") else 0
    return {"ok": True, "key": key,
            "detail": f"{n} key{'s' if n != 1 else ''} saved" if n else "saved"}
