"""Config loading + interactive wizard. Part 0 foundation.

- load_config(auto_wizard=True, demo=False) -> AppConfig
- Missing .env -> copy from .env.example + prompt only missing keys.
- Demo mode bypasses required keys with placeholders.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"


class ConfigError(Exception):
    """User-friendly config error with fix hint."""


@dataclass
class AppConfig:
    gemini_api_key: str = ""
    groq_api_key: str = ""
    llm_model: str = "gemini-3.6-flash"
    groq_model: str = "openai/gpt-oss-120b"
    rapidapi_key: str = ""
    rapidapi_host: str = "jsearch.p.rapidapi.com"
    rapidapi_job_endpoint: str = "https://jsearch.p.rapidapi.com/job-details"
    rapidapi_search_endpoint: str = "https://jsearch.p.rapidapi.com/search-v2"
    rapidapi_country: str = "in"
    google_sheet_id: str = ""
    google_credentials_file: str = "credentials.json"
    applicant_name: str = "Chaitanya Jain"
    linkedin_profile_url: str = ""
    linkedin_profile_file: str = "profile.md"
    demo: bool = False

    @property
    def has_llm_key(self) -> bool:
        return bool(self.gemini_api_key or self.groq_api_key)


# key in .env -> (attr, required_for_real_run, prompt_text)
_MANAGED_KEYS: list[tuple[str, str, bool, str]] = [
    ("GEMINI_API_KEY", "gemini_api_key", True, "Gemini API key (https://aistudio.google.com/app/apikey)"),
    ("GROQ_API_KEY", "groq_api_key", False, "Groq API key (optional fallback, Enter to skip)"),
    ("GROQ_MODEL", "groq_model", False, "Groq model [openai/gpt-oss-120b]"),
    ("LLM_MODEL", "llm_model", False, "LLM model [gemini-3.6-flash]"),
    ("RAPIDAPI_KEY", "rapidapi_key", True, "RapidAPI key (https://rapidapi.com, subscribe JSearch free)"),
    ("RAPIDAPI_HOST", "rapidapi_host", False, "RapidAPI host [jsearch.p.rapidapi.com]"),
    ("RAPIDAPI_JOB_ENDPOINT", "rapidapi_job_endpoint", False, "RapidAPI job endpoint URL"),
    ("RAPIDAPI_SEARCH_ENDPOINT", "rapidapi_search_endpoint", False, "RapidAPI search URL [search-v2]"),
    ("RAPIDAPI_COUNTRY", "rapidapi_country", False, "JSearch country bias [in]"),
    ("GOOGLE_SHEET_ID", "google_sheet_id", True, "Google Sheet ID (from sheet URL between /d/ and /edit)"),
    ("GOOGLE_CREDENTIALS_FILE", "google_credentials_file", False, "Google OAuth credentials file [credentials.json]"),
    ("APPLICANT_NAME", "applicant_name", False, "Your name for resume filenames [Chaitanya Jain]"),
    ("LINKEDIN_PROFILE_URL", "linkedin_profile_url", False, "LinkedIn profile URL (optional, Enter to skip)"),
    ("LINKEDIN_PROFILE_FILE", "linkedin_profile_file", False, "Local profile supplement [profile.md]"),
]


def _ensure_env_file_exists() -> None:
    if ENV_PATH.exists():
        return
    if ENV_EXAMPLE.exists():
        shutil.copy(ENV_EXAMPLE, ENV_PATH)
        print(f"Created {ENV_PATH.name} from .env.example. Please fill missing keys (or run with --demo).")
    else:
        ENV_PATH.touch()
        print(f"Created empty {ENV_PATH.name}.")


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def _write_dotenv(path: Path, values: dict[str, str]) -> None:
    # Preserve example comments by rewriting known keys only; keep it simple.
    lines: list[str] = []
    for env_key, _, _, _ in _MANAGED_KEYS:
        lines.append(f"{env_key}={values.get(env_key, '')}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _open_key_page(url: str, open_browser: bool) -> None:
    if not url or not open_browser:
        return
    try:
        import webbrowser
        webbrowser.open(url)
        print(f"(opened in browser: {url})")
    except Exception:
        pass  # headless/SSH: the printed link suffices


def run_setup_wizard(open_browser: bool = True) -> AppConfig:
    """Guided setup: per-item instructions + key-page links, validated paste.

    Prompts only for missing/invalid items; saves incrementally so Ctrl+C
    keeps progress. Silent defaults fill the advanced keys.
    """
    from src.setup_guide import SETUP_ITEMS, check_credentials_file, validate_item
    from src.utils import PROJECT_ROOT
    _ensure_env_file_exists()
    values = _read_dotenv(ENV_PATH)
    # Also respect real environment variables (CI).
    for env_key, _, _, _ in _MANAGED_KEYS:
        if not values.get(env_key) and os.environ.get(env_key):
            values[env_key] = os.environ[env_key]

    # Silent defaults for advanced keys (never prompted).
    _SILENT_DEFAULTS = {
        "LLM_MODEL": "gemini-3.6-flash",
        "GROQ_MODEL": "openai/gpt-oss-120b",
        "RAPIDAPI_HOST": "jsearch.p.rapidapi.com",
        "RAPIDAPI_JOB_ENDPOINT": "https://jsearch.p.rapidapi.com/job-details",
        "RAPIDAPI_SEARCH_ENDPOINT": "https://jsearch.p.rapidapi.com/search-v2",
        "RAPIDAPI_COUNTRY": "in",
        "GOOGLE_CREDENTIALS_FILE": "credentials.json",
        "LINKEDIN_PROFILE_URL": "",
        "LINKEDIN_PROFILE_FILE": "profile.md",
    }
    for k, default in _SILENT_DEFAULTS.items():
        if not values.get(k):
            values[k] = default

    print("\n== JobHunt guided setup ==")
    print("Each step shows where to get the value; the page opens automatically.")
    print("Blank = keep existing / skip optional. Ctrl+C keeps saved progress.\n")

    # Gemini is satisfiable via Groq alone (mirrors _missing_required).
    groq_ok = bool(values.get("GROQ_API_KEY", "").strip())

    for it in SETUP_ITEMS:
        if it.kind == "file":
            if _wizard_file_item(it, open_browser) is None:
                break  # user cancelled
            continue
        current = values.get(it.key, "")
        if it.key == "GEMINI_API_KEY" and groq_ok and not current:
            print(f"[skip] {it.title} — Groq key present, Gemini optional.\n")
            continue
        ok, _ = validate_item(it, current)
        if ok and current:
            print(f"[ok] {it.title} — already set.\n")
            continue
        if _wizard_env_item(it, values, open_browser) is None:
            break  # user cancelled
        if it.key == "GROQ_API_KEY" and values.get("GROQ_API_KEY", "").strip():
            groq_ok = True

    _write_dotenv(ENV_PATH, values)
    print(f"\nSaved to {ENV_PATH}. Run 'python agent.py doctor' to verify.")
    return _from_values(values, demo=False)


def _wizard_env_item(it, values: dict, open_browser: bool):
    """Prompt-validate loop for one env item. Returns False-ish None on cancel."""
    from src.setup_guide import validate_item
    print(f"--- {it.title} ---")
    if it.why:
        print(it.why)
    for i, step in enumerate(it.steps, 1):
        print(f"  {i}. {step}")
    if it.open_url:
        print(f"  Link: {it.open_url}")
        _open_key_page(it.open_url, open_browser)
    while True:
        try:
            hint = ""
            if it.optional:
                hint = " (Enter to skip)"
            elif it.default:
                hint = f" (Enter for '{it.default}')"
            answer = input(f"Paste {it.title}{hint}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSetup paused (progress saved).")
            return None
        if not answer and it.optional:
            print("(skipped)\n")
            return True
        if not answer and it.default:
            values[it.key] = it.default
            _write_dotenv(ENV_PATH, values)
            print(f"Using default: {it.default}\n")
            return True
        if not answer:
            print("This one is required — paste the value, or Ctrl+C to pause.\n")
            continue
        ok, msg = validate_item(it, answer)
        if ok:
            from src.setup_guide import extract_sheet_id
            values[it.key] = (extract_sheet_id(answer) if it.key == "GOOGLE_SHEET_ID"
                              else answer)
            _write_dotenv(ENV_PATH, values)
            print("Saved.\n")
            return True
        print(f"That doesn't look right: {msg}\nTry again (Ctrl+C pauses, keeps progress).\n")


def _wizard_file_item(it, open_browser: bool):
    """Check-and-guide for file items. Returns None on cancel."""
    from src.setup_guide import check_credentials_file
    from src.utils import PROJECT_ROOT
    if it.key == "credentials.json":
        err = check_credentials_file(PROJECT_ROOT / "credentials.json")
        if not err:
            print("[ok] Google OAuth client file — found.\n")
            return True
        print(f"--- {it.title} ---")
        for i, step in enumerate(it.steps, 1):
            print(f"  {i}. {step}")
        print(f"  Link: {it.open_url}")
        _open_key_page(it.open_url, open_browser)
        while True:
            try:
                answer = input("Press Enter when the file is placed "
                               "(or type 'skip'): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nSetup paused (progress saved).")
                return None
            if answer == "skip":
                print("(skipped — Gmail/Sheets steps will fail until added)\n")
                return True
            err = check_credentials_file(PROJECT_ROOT / "credentials.json")
            if not err:
                print("Found and valid.\n")
                return True
            print(f"Still not right: {err}\n")
    elif it.key == "main.tex":
        from src.utils import PROJECT_ROOT as _PR
        if (_PR / "main.tex").is_file():
            print("[ok] Base resume — main.tex found.\n")
            return True
        print("[!!] Base resume — main.tex missing (tailoring needs it).")
        print("Give a .tex file path and it will be copied into place.\n")
        from src.setup_guide import install_base_resume
        while True:
            try:
                answer = input("Path to your .tex resume (Enter to skip): ").strip().strip('"').strip("'")
            except (EOFError, KeyboardInterrupt):
                print("\nSetup paused (progress saved).")
                return None
            if not answer:
                print("(skipped — add main.tex later)\n")
                return True
            from pathlib import Path as _P
            src = _P(answer).expanduser()
            if not src.is_file():
                print(f"Not found: {answer}\n")
                continue
            try:
                content = src.read_text(encoding="utf-8")
            except Exception as e:
                print(f"Couldn't read it: {e}\n")
                continue
            if (_PR / "main.tex").is_file():
                try:
                    go = input("main.tex appeared meanwhile — replace it? [y/N]: ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print("\nSetup paused (progress saved).")
                    return None
                if go != "y":
                    print("(kept existing)\n")
                    return True
            try:
                res = install_base_resume(content, _PR)
            except ValueError as e:
                print(f"Not usable: {e}\n")
                continue
            extra = f" (previous kept as {res['backup']})" if res["replaced"] else ""
            print(f"Installed as main.tex{extra}.\n")
            return True
    elif it.key == "profile.md":
        from src.utils import PROJECT_ROOT as _PR2
        if (_PR2 / "profile.md").is_file():
            print("[ok] LinkedIn supplement — profile.md found.\n")
            return True
        try:
            answer = input("Copy profile.md.example to profile.md now? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nSetup paused (progress saved).")
            return None
        if answer == "y":
            try:
                import shutil
                shutil.copy(_PR2 / "profile.md.example", _PR2 / "profile.md")
                print("Created profile.md — paste your About + Skills into it.\n")
            except Exception as e:
                print(f"Couldn't copy: {e}\n")
        else:
            print("(skipped — optional)\n")
        return True
    return True


def _from_values(values: dict[str, str], demo: bool) -> AppConfig:
    # env vars take precedence over .env file; blank entries fall back to
    # defaults (setup writes every managed key, so newly added keys would
    # otherwise shadow their defaults with empty strings)
    def get(key: str, default: str = "") -> str:
        v = os.environ.get(key, values.get(key, ""))
        return (v.strip() if v else "") or default

    return AppConfig(
        gemini_api_key=get("GEMINI_API_KEY"),
        groq_api_key=get("GROQ_API_KEY"),
        llm_model=get("LLM_MODEL", "gemini-3.6-flash"),
        groq_model=get("GROQ_MODEL", "openai/gpt-oss-120b"),
        rapidapi_key=get("RAPIDAPI_KEY"),
        rapidapi_host=get("RAPIDAPI_HOST", "jsearch.p.rapidapi.com"),
        rapidapi_job_endpoint=get("RAPIDAPI_JOB_ENDPOINT", "https://jsearch.p.rapidapi.com/job-details"),
        rapidapi_search_endpoint=get("RAPIDAPI_SEARCH_ENDPOINT", "https://jsearch.p.rapidapi.com/search-v2"),
        rapidapi_country=get("RAPIDAPI_COUNTRY", "in"),
        google_sheet_id=get("GOOGLE_SHEET_ID"),
        google_credentials_file=get("GOOGLE_CREDENTIALS_FILE", "credentials.json"),
        applicant_name=get("APPLICANT_NAME", "Chaitanya Jain"),
        linkedin_profile_url=get("LINKEDIN_PROFILE_URL"),
        linkedin_profile_file=get("LINKEDIN_PROFILE_FILE", "profile.md"),
        demo=demo,
    )


def load_config(auto_wizard: bool = True, demo: bool = False) -> AppConfig:
    """Load config from .env + environment.

    demo=True -> never fails on missing keys (placeholders).
    auto_wizard=True + interactive terminal + missing keys -> prompt once.
    """
    _ensure_env_file_exists()
    values = _read_dotenv(ENV_PATH)
    cfg = _from_values(values, demo=demo)

    if demo:
        if not cfg.gemini_api_key:
            cfg.gemini_api_key = "demo"
        if not cfg.rapidapi_key:
            cfg.rapidapi_key = "demo"
        if not cfg.google_sheet_id:
            cfg.google_sheet_id = "demo"
        return cfg

    missing = _missing_required(cfg)
    if missing and auto_wizard and _is_interactive():
        print(f"Missing {len(missing)} required key(s): {', '.join(missing)}")
        return run_setup_wizard()

    if missing:
        raise ConfigError(
            f"Missing required config: {', '.join(missing)}. "
            f"Fix: run 'python agent.py setup' or 'python agent.py doctor', "
            f"or use '--demo' for offline trial."
        )
    return cfg


def _missing_required(cfg: AppConfig) -> list[str]:
    missing: list[str] = []
    if not cfg.gemini_api_key and not cfg.groq_api_key:
        missing.append("GEMINI_API_KEY (or GROQ_API_KEY)")
    if not cfg.rapidapi_key:
        missing.append("RAPIDAPI_KEY")
    if not cfg.google_sheet_id:
        missing.append("GOOGLE_SHEET_ID")
    return missing


def _is_interactive() -> bool:
    try:
        import sys
        return sys.stdin.isatty()
    except Exception:
        return False
