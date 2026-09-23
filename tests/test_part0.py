"""Part 0 tests: config + CLI routing + doctor. All offline."""
from __future__ import annotations

from pathlib import Path

import src.config as C
from src.cli import normalize_args
from src.doctor import run_doctor


def _write_env(path: Path, text: str):
    path.write_text(text, encoding="utf-8")


def test_load_valid_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    _write_env(env, "GEMINI_API_KEY=g1\nRAPIDAPI_KEY=r1\nGOOGLE_SHEET_ID=s1\n")
    monkeypatch.setattr(C, "ENV_PATH", env)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    cfg = C.load_config(auto_wizard=False, demo=False)
    assert cfg.gemini_api_key == "g1"
    assert cfg.rapidapi_key == "r1"
    assert cfg.google_sheet_id == "s1"


def test_missing_key_raises_friendly(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    _write_env(env, "GEMINI_API_KEY=\nRAPIDAPI_KEY=\nGOOGLE_SHEET_ID=\n")
    monkeypatch.setattr(C, "ENV_PATH", env)
    for k in ["GEMINI_API_KEY", "GROQ_API_KEY", "RAPIDAPI_KEY", "GOOGLE_SHEET_ID"]:
        monkeypatch.delenv(k, raising=False)
    try:
        C.load_config(auto_wizard=False, demo=False)
        assert False, "should raise"
    except C.ConfigError as e:
        msg = str(e)
        assert "GEMINI_API_KEY" in msg or "RAPIDAPI_KEY" in msg
        assert "--demo" in msg or "setup" in msg


def test_demo_mode_skips_keys(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    _write_env(env, "")
    monkeypatch.setattr(C, "ENV_PATH", env)
    for k in ["GEMINI_API_KEY", "GROQ_API_KEY", "RAPIDAPI_KEY", "GOOGLE_SHEET_ID"]:
        monkeypatch.delenv(k, raising=False)
    cfg = C.load_config(auto_wizard=False, demo=True)
    assert cfg.demo is True
    assert cfg.gemini_api_key == "demo"


def test_wizard_creates_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    ex = tmp_path / ".env.example"
    ex.write_text("GEMINI_API_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(C, "ENV_PATH", env)
    monkeypatch.setattr(C, "ENV_EXAMPLE", ex)
    answers = iter(["g-wiz", "", "", "", "r-wiz", "", "", "", "", "s-wiz", ""])
    monkeypatch.setattr("builtins.input", lambda _="": next(answers))
    cfg = C.run_setup_wizard()
    assert env.exists()
    assert cfg.gemini_api_key == "g-wiz"
    assert cfg.rapidapi_key == "r-wiz"


def test_doctor_reports_tectonic_missing(monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda _: None)
    results = run_doctor()
    tec = [r for r in results if "tectonic" in r.name][0]
    assert tec.ok is False
    assert "tectonic" in (tec.fix + tec.detail).lower()


def test_cli_bare_url_routes_to_apply():
    ns = normalize_args(['https://www.linkedin.com/jobs/view/4012345678'])
    assert ns.command == "apply"
    assert "4012345678" in ns.url


def test_cli_check_mail_flag():
    ns = normalize_args(['--check-mail'])
    assert ns.command == "check-mail"


def test_cli_apply_requires_url():
    import pytest
    with pytest.raises(SystemExit):
        normalize_args(['apply'])
