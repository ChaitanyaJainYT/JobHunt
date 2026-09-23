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
    google_sheet_id: str = ""
    google_credentials_file: str = "credentials.json"
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
    ("GOOGLE_SHEET_ID", "google_sheet_id", True, "Google Sheet ID (from sheet URL between /d/ and /edit)"),
    ("GOOGLE_CREDENTIALS_FILE", "google_credentials_file", False, "Google OAuth credentials file [credentials.json]"),
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


def run_setup_wizard() -> AppConfig:
    """Interactively ask for missing keys and save .env. Returns loaded config."""
    _ensure_env_file_exists()
    values = _read_dotenv(ENV_PATH)
    # Also respect real environment variables (CI).
    for env_key, _, _, _ in _MANAGED_KEYS:
        if not values.get(env_key) and os.environ.get(env_key):
            values[env_key] = os.environ[env_key]

    print("\n== JobHunt setup ==")
    print("Press Enter to keep [default] / skip optional keys.\n")
    for env_key, attr, required, prompt in _MANAGED_KEYS:
        current = values.get(env_key, "")
        if current and required:
            continue  # already set, don't re-ask
        try:
            answer = input(f"{prompt}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSetup cancelled.")
            break
        if answer:
            values[env_key] = answer
        elif env_key == "LLM_MODEL" and not values.get(env_key):
            values[env_key] = "gemini-3.6-flash"
        elif env_key == "GROQ_MODEL" and not values.get(env_key):
            values[env_key] = "openai/gpt-oss-120b"
        elif env_key == "RAPIDAPI_HOST" and not values.get(env_key):
            values[env_key] = "jsearch.p.rapidapi.com"
        elif env_key == "RAPIDAPI_JOB_ENDPOINT" and not values.get(env_key):
            values[env_key] = "https://jsearch.p.rapidapi.com/job-details"
        elif env_key == "GOOGLE_CREDENTIALS_FILE" and not values.get(env_key):
            values[env_key] = "credentials.json"

    _write_dotenv(ENV_PATH, values)
    print(f"\nSaved to {ENV_PATH}. You can re-run with: python agent.py doctor")
    return _from_values(values, demo=False)


def _from_values(values: dict[str, str], demo: bool) -> AppConfig:
    # env vars take precedence over .env file
    def get(key: str, default: str = "") -> str:
        return os.environ.get(key, values.get(key, default)).strip()

    return AppConfig(
        gemini_api_key=get("GEMINI_API_KEY"),
        groq_api_key=get("GROQ_API_KEY"),
        llm_model=get("LLM_MODEL", "gemini-3.6-flash"),
        groq_model=get("GROQ_MODEL", "openai/gpt-oss-120b"),
        rapidapi_key=get("RAPIDAPI_KEY"),
        rapidapi_host=get("RAPIDAPI_HOST", "jsearch.p.rapidapi.com"),
        rapidapi_job_endpoint=get("RAPIDAPI_JOB_ENDPOINT", "https://jsearch.p.rapidapi.com/job-details"),
        google_sheet_id=get("GOOGLE_SHEET_ID"),
        google_credentials_file=get("GOOGLE_CREDENTIALS_FILE", "credentials.json"),
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
