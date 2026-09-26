"""setup_guide tests: validators (offline), state/save roundtrips, no network."""
from __future__ import annotations

import json

import pytest

import src.setup_guide as G


def _no_net(monkeypatch):
    import socket
    def boom(*a, **k):
        raise AssertionError("network used during setup (must stay offline)")
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(socket, "getaddrinfo", boom)


def test_gemini_validator():
    assert G.valid_gemini_key("AIza" + "x" * 35) is None
    assert G.valid_gemini_key("AIza" + "x" * 35 + "," + "AIza" + "y" * 35) is None
    assert G.valid_gemini_key("AQ.A" + "z" * 49) is None  # other Google-issued shape
    assert G.valid_gemini_key("") is not None
    assert G.valid_gemini_key("AIza-short") is not None
    assert G.valid_gemini_key("AIza" + "x" * 35 + ", nope") is not None
    assert G.valid_gemini_key("https://example.com/key") is not None


def test_groq_validator_optional():
    assert G.valid_groq_key("") is None
    assert G.valid_groq_key("gsk_" + "a" * 20) is None
    assert G.valid_groq_key("bad") is not None


def test_rapidapi_validator():
    assert G.valid_rapidapi_key("x" * 50) is None
    assert G.valid_rapidapi_key("x" * 50 + ", " + "y" * 50) is None
    assert G.valid_rapidapi_key("short") is not None
    assert G.valid_rapidapi_key("") is not None


def test_sheet_id_extraction():
    assert G.extract_sheet_id("https://docs.google.com/spreadsheets/d/ABC123xyz-_q/edit") == "ABC123xyz-_q"
    assert G.extract_sheet_id("ABC123xyz-_qWERTY1234567890abcd") == "ABC123xyz-_qWERTY1234567890abcd"
    assert G.extract_sheet_id("not a url") == ""
    assert G.valid_sheet_id("https://docs.google.com/spreadsheets/d/ABC123xyz-_q/edit") is None
    assert G.valid_sheet_id("") is not None


def test_credentials_file_check(tmp_path):
    missing = tmp_path / "credentials.json"
    assert G.check_credentials_file(missing) is not None
    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    assert G.check_credentials_file(bad) is not None
    web = tmp_path / "web.json"
    web.write_text(json.dumps({"web": {"client_id": "x"}}), encoding="utf-8")
    assert G.check_credentials_file(web) is not None  # must be Desktop type
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"installed": {"client_id": "x.apps.googleusercontent.com"}}),
                    encoding="utf-8")
    assert G.check_credentials_file(good) is None


def _env(monkeypatch, tmp_path, text):
    import src.config as C
    env = tmp_path / ".env"
    env.write_text(text, encoding="utf-8")
    monkeypatch.setattr(C, "ENV_PATH", env)
    for k in ["GEMINI_API_KEY", "GROQ_API_KEY", "RAPIDAPI_KEY", "GOOGLE_SHEET_ID"]:
        monkeypatch.delenv(k, raising=False)
    return env


def test_state_reports_without_secrets(tmp_path, monkeypatch):
    _no_net(monkeypatch)
    _env(monkeypatch, tmp_path, "GEMINI_API_KEY=AIza" + "x" * 35 + "\n")
    import src.utils as UT
    monkeypatch.setattr(UT, "PROJECT_ROOT", tmp_path)
    state = G.get_setup_state()
    by_key = {s["key"]: s for s in state}
    assert by_key["GEMINI_API_KEY"]["status"] == "ready"
    assert by_key["RAPIDAPI_KEY"]["status"] == "missing"
    assert by_key["GROQ_API_KEY"]["status"] == "skipped"
    blob = json.dumps(state)
    assert "AIza" + "x" * 35 not in blob  # pasted values never leak
    assert "open_url" in blob and "steps" in blob


def test_save_roundtrip_and_rejection(tmp_path, monkeypatch):
    _no_net(monkeypatch)
    _env(monkeypatch, tmp_path, "")
    res = G.save_setup_value("GEMINI_API_KEY", "AIza" + "x" * 35)
    assert res["ok"] and "1 key" in res["detail"]
    with pytest.raises(ValueError):
        G.save_setup_value("GEMINI_API_KEY", "junk")
    with pytest.raises(ValueError):
        G.save_setup_value("NOPE_KEY", "x")
    res = G.save_setup_value("GOOGLE_SHEET_ID",
                             "https://docs.google.com/spreadsheets/d/ABC123xyz-_q/edit")
    assert res["ok"]
    import src.config as C
    assert "ABC123xyz-_q\n" in C.ENV_PATH.read_text(encoding="utf-8")


def test_install_base_resume(tmp_path):
    good = "\\documentclass{article}\n\\begin{document}\nHi\n\\end{document}"
    res = G.install_base_resume(good, tmp_path)
    assert res == {"file": "main.tex", "replaced": False, "backup": None}
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == good
    res = G.install_base_resume(good.replace("Hi", "Yo"), tmp_path)
    assert res["replaced"] is True and res["backup"] == "main.tex.bak"
    assert (tmp_path / "main.tex.bak").read_text(encoding="utf-8") == good
    import pytest as _p
    with _p.raises(ValueError):
        G.install_base_resume("   ", tmp_path)
    with _p.raises(ValueError):
        G.install_base_resume("just prose, no latex", tmp_path)
    with _p.raises(ValueError):
        G.install_base_resume("x" * (G.MAX_RESUME_BYTES + 1), tmp_path)


def test_multi_key_counts(tmp_path, monkeypatch):
    _no_net(monkeypatch)
    _env(monkeypatch, tmp_path, "")
    res = G.save_setup_value("GROQ_API_KEY", "gsk_" + "a" * 20 + ",gsk_" + "b" * 20)
    assert "2 keys" in res["detail"]
