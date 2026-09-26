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


def test_blank_values_fall_back_to_defaults():
    cfg = C._from_values({"LLM_MODEL": "", "RAPIDAPI_SEARCH_ENDPOINT": "",
                          "RAPIDAPI_COUNTRY": "", "GEMINI_API_KEY": ""}, demo=False)
    assert cfg.llm_model == "gemini-3.6-flash"
    assert cfg.rapidapi_search_endpoint == "https://jsearch.p.rapidapi.com/search-v2"
    assert cfg.rapidapi_country == "in"
    assert cfg.gemini_api_key == ""  # required keys must stay detectable-as-missing


def test_demo_mode_skips_keys(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    _write_env(env, "")
    monkeypatch.setattr(C, "ENV_PATH", env)
    for k in ["GEMINI_API_KEY", "GROQ_API_KEY", "RAPIDAPI_KEY", "GOOGLE_SHEET_ID"]:
        monkeypatch.delenv(k, raising=False)
    cfg = C.load_config(auto_wizard=False, demo=True)
    assert cfg.demo is True
    assert cfg.gemini_api_key == "demo"


def test_wizard_guided_flow(tmp_path, monkeypatch):
    import json as _json
    import src.utils as UT
    env = tmp_path / ".env"
    ex = tmp_path / ".env.example"
    ex.write_text("GEMINI_API_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(C, "ENV_PATH", env)
    monkeypatch.setattr(C, "ENV_EXAMPLE", ex)
    monkeypatch.setattr(UT, "PROJECT_ROOT", tmp_path)
    (tmp_path / "main.tex").write_text("resume", encoding="utf-8")
    (tmp_path / "credentials.json").write_text(
        _json.dumps({"installed": {"client_id": "x.apps.googleusercontent.com"}}),
        encoding="utf-8")
    (tmp_path / "profile.md.example").write_text("# template", encoding="utf-8")
    answers = iter(["AIza" + "g" * 35, "", "r" * 50,
                    "https://docs.google.com/spreadsheets/d/SHEETID1234567890ab/edit",
                    "", "n"])
    monkeypatch.setattr("builtins.input", lambda _="": next(answers))
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    cfg = C.run_setup_wizard()
    assert env.exists()
    assert cfg.gemini_api_key == "AIza" + "g" * 35
    assert cfg.rapidapi_key == "r" * 50
    assert cfg.google_sheet_id == "SHEETID1234567890ab"
    assert cfg.applicant_name == "Chaitanya Jain"  # default accepted
    assert opened == ["https://aistudio.google.com/app/apikey",
                      "https://console.groq.com/keys",
                      "https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch",
                      "https://sheets.google.com"]


def test_wizard_no_open_flag(tmp_path, monkeypatch):
    import src.utils as UT
    env = tmp_path / ".env"
    env.write_text("GEMINI_API_KEY=AIza" + "g" * 35 + "\n"
                   "RAPIDAPI_KEY=" + "r" * 50 + "\n"
                   "GOOGLE_SHEET_ID=" + "S" * 44 + "\n", encoding="utf-8")
    monkeypatch.setattr(C, "ENV_PATH", env)
    monkeypatch.setattr(UT, "PROJECT_ROOT", tmp_path)
    (tmp_path / "main.tex").write_text("resume", encoding="utf-8")
    (tmp_path / "credentials.json").write_text('{"installed": {"client_id": "x"}}',
                                               encoding="utf-8")
    (tmp_path / "profile.md").write_text("# me", encoding="utf-8")
    answers = iter(["", "", ""])  # groq skip, applicant default, (profile exists: no prompt)
    monkeypatch.setattr("builtins.input", lambda _="": next(answers))
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    C.run_setup_wizard(open_browser=False)
    assert opened == []


def _main_tex_item():
    import src.setup_guide as G
    return next(i for i in G.SETUP_ITEMS if i.key == "main.tex")


def test_wizard_copies_base_resume(tmp_path, monkeypatch):
    import src.utils as UT
    monkeypatch.setattr(UT, "PROJECT_ROOT", tmp_path)
    src = tmp_path / "resume.tex"
    src.write_text("\\documentclass{a}\n\\begin{document}\nHi\n\\end{document}",
                   encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _: str(src))
    assert C._wizard_file_item(_main_tex_item(), False) is True
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == src.read_text(encoding="utf-8")


def test_wizard_skips_prompt_when_present(tmp_path, monkeypatch):
    import src.utils as UT
    monkeypatch.setattr(UT, "PROJECT_ROOT", tmp_path)
    (tmp_path / "main.tex").write_text("old", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(AssertionError("no prompt expected")))
    assert C._wizard_file_item(_main_tex_item(), False) is True  # exists: no prompt
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == "old"


def test_wizard_rejects_non_latex(tmp_path, monkeypatch, capsys):
    import src.utils as UT
    monkeypatch.setattr(UT, "PROJECT_ROOT", tmp_path)
    src = tmp_path / "notes.txt"
    src.write_text("just prose", encoding="utf-8")
    answers = iter([str(src), ""])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert C._wizard_file_item(_main_tex_item(), False) is True
    assert not (tmp_path / "main.tex").exists()
    assert "Not usable" in capsys.readouterr().out


def test_doctor_reports_tectonic_missing(monkeypatch):
    import shutil
    import src.compiler as Cp
    monkeypatch.setattr(shutil, "which", lambda _: None)
    monkeypatch.setattr(Cp, "bundled_tectonic", lambda: None)
    results = run_doctor()
    tec = [r for r in results if "tectonic" in r.name][0]
    assert tec.ok is False
    assert "tectonic" in (tec.fix + tec.detail).lower()


def test_doctor_accepts_bundled_tectonic(monkeypatch, tmp_path):
    import shutil
    import src.compiler as Cp
    monkeypatch.setattr(shutil, "which", lambda _: None)
    monkeypatch.setattr(Cp, "bundled_tectonic", lambda: tmp_path / "tectonic.exe")
    results = run_doctor()
    tec = [r for r in results if "tectonic" in r.name][0]
    assert tec.ok is True
    assert "bundled" in tec.detail


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
