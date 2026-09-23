"""Part 3 tests: tailor + compiler/self-heal (mocked)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import src.tailor as T
import src.compiler as Cp
from src import llm

BASE = "\\documentclass{article}\n\\begin{document}\nPython dev.\n\\end{document}\n"


def test_tailor_preserves_commands(monkeypatch):
    out = BASE.replace("Python dev.", "Senior Python dev.")
    monkeypatch.setattr(llm, "complete_text", lambda *a, **k: out)
    r = T.tailor_resume(BASE, "Senior Python Dev", "Acme", ["aws"], ["python"], api_key="x")
    assert "\\documentclass" in r and "\\begin{document}" in r


def test_tailor_rejects_non_tex(monkeypatch):
    monkeypatch.setattr(llm, "complete_text", lambda *a, **k: "hello")
    with pytest.raises(ValueError):
        T.tailor_resume(BASE, "T", "C", [], [], api_key="x")


def test_tailor_saves_file(tmp_path):
    p = T.save_tailored(BASE, tmp_path, "Acme Corp!")
    assert p.exists() and p.suffix == ".tex"


def _run_ok(*a, **k):
    class R:
        returncode = 0
        stdout = ""
        stderr = ""
    return R()


def test_compile_success(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: "C:/fake/tectonic.exe")
    monkeypatch.setattr(subprocess, "run", _run_ok)
    tex = tmp_path / "R.tex"
    tex.write_text(BASE, encoding="utf-8")
    (tmp_path / "R.pdf").write_text("fake-pdf", encoding="utf-8")
    assert Cp.compile_tex(tex).suffix == ".pdf"


def test_compile_missing_tectonic(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    monkeypatch.setattr(Cp, "bundled_tectonic", lambda: None)
    with pytest.raises(Cp.LatexCompileError, match="tectonic-typesetting"):
        Cp.compile_tex(tmp_path / "R.tex")


def test_find_tectonic_prefers_bundled(tmp_path, monkeypatch):
    fake = tmp_path / "tectonic.exe"
    fake.write_bytes(b"x")
    monkeypatch.setattr(Cp, "bundled_tectonic", lambda: fake)
    monkeypatch.setattr("shutil.which", lambda _: "C:/other/tectonic.exe")
    assert Cp.find_tectonic() == str(fake)


def test_find_tectonic_falls_back_to_path(tmp_path, monkeypatch):
    monkeypatch.setattr(Cp, "bundled_tectonic", lambda: None)
    monkeypatch.setattr("shutil.which", lambda _: "C:/other/tectonic.exe")
    assert Cp.find_tectonic() == "C:/other/tectonic.exe"


def test_self_heal_retries(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: "tectonic")
    calls = {"n": 0}
    def run(*a, **k):
        calls["n"] += 1
        class R:
            stdout = "err log"
            stderr = ""
            returncode = 0 if calls["n"] >= 2 else 1
        return R()
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(llm, "fix_latex", lambda *a, **k: BASE)
    tex = tmp_path / "R.tex"
    tex.write_text("broken", encoding="utf-8")
    (tmp_path / "R.pdf").write_text("pdf", encoding="utf-8")
    assert Cp.compile_with_heal(tex, api_key="x").suffix == ".pdf"
    assert calls["n"] == 2


def test_self_heal_gives_up_gracefully(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: "tectonic")
    def run(*a, **k):
        class R:
            returncode = 1
            stdout = "bad"
            stderr = ""
        return R()
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(llm, "fix_latex", lambda *a, **k: BASE)
    tex = tmp_path / "R.tex"
    tex.write_text("broken", encoding="utf-8")
    with pytest.raises(Cp.LatexCompileError):
        Cp.compile_with_heal(tex, api_key="x", max_retries=1)
    assert tex.exists()
    assert (tmp_path / "R.tectonic.log").exists()
