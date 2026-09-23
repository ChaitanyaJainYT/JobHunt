"""UI backend tests: path safety, job listing, task validation (no network)."""
from __future__ import annotations

import json

import pytest

import ui as U


def test_safe_path_rejects_escape(tmp_path, monkeypatch):
    import src.utils as UT
    monkeypatch.setattr(UT, "OUTPUT_ROOT", tmp_path)
    assert U.safe_output_path("../agent.py") is None
    assert U.safe_output_path("..") is None
    assert U.safe_output_path("missing.pdf") is None


def test_safe_path_allows_output_file(tmp_path, monkeypatch):
    import src.utils as UT
    monkeypatch.setattr(UT, "OUTPUT_ROOT", tmp_path)
    d = tmp_path / "Acme_1"
    d.mkdir()
    (d / "R.pdf").write_bytes(b"%PDF")
    p = U.safe_output_path("Acme_1/R.pdf")
    assert p is not None and p.name == "R.pdf"


def test_list_jobs_reads_artifacts(tmp_path, monkeypatch):
    import src.utils as UT
    monkeypatch.setattr(UT, "OUTPUT_ROOT", tmp_path)
    d = tmp_path / "Acme_1"
    d.mkdir()
    (d / "job.json").write_text(json.dumps({
        "company": "Acme", "title": "Dev", "apply_link": "https://apply/1"}))
    (d / "match.json").write_text(json.dumps({
        "match_score": 80, "matching_skills": ["python"], "missing_skills": []}))
    (d / "Acme_Resume.pdf").write_bytes(b"%PDF")
    jobs = U.list_jobs()
    assert len(jobs) == 1
    assert jobs[0]["match_score"] == 80
    assert jobs[0]["pdf_url"].endswith(".pdf")


def test_list_jobs_empty_without_output(tmp_path, monkeypatch):
    import src.utils as UT
    monkeypatch.setattr(UT, "OUTPUT_ROOT", tmp_path / "nope")
    assert U.list_jobs() == []


def test_start_apply_rejects_bad_url():
    with pytest.raises(ValueError, match="http"):
        U.start_apply_task("not-a-url")


def test_task_registry_roundtrip():
    tid, task = U._new_task("apply")
    assert U.get_task(tid)["status"] == "running"
    assert U.get_task("nope") is None


def test_console_help_and_setup():
    out = U.console_dispatch("help")
    assert "doctor" in out["output"]
    out = U.console_dispatch("python agent.py --help")
    assert "doctor" in out["output"]
    out = U.console_dispatch("setup")
    assert "terminal" in out["output"].lower()


def test_console_rejects_unknown():
    res = U.console_dispatch("rm -rf /")
    assert "error" in res
    res = U.console_dispatch("")
    assert "output" in res  # empty -> help


def _wait_done(tid, timeout_s=30):
    import time
    end = time.time() + timeout_s
    while time.time() < end:
        t = U.get_task(tid)
        if t and t["status"] != "running":
            return t
        time.sleep(0.2)
    raise TimeoutError(tid)


def test_console_doctor_task():
    res = U.console_dispatch("doctor")
    assert "task_id" in res
    t = _wait_done(res["task_id"])
    assert t["status"] == "done"
    assert any("JobHunt doctor" in line for line in t["log"])


def test_console_apply_demo_task():
    res = U.console_dispatch('apply "https://www.linkedin.com/jobs/view/4012345678" --demo')
    assert "task_id" in res
    t = _wait_done(res["task_id"])
    assert t["status"] == "done"
    assert t["result"].get("exit_code") == 0


def test_console_check_mail_demo_task(tmp_path):
    import src.gmail as G
    orig = G.SEEN_DEFAULT
    G.SEEN_DEFAULT = tmp_path / "seen.json"
    try:
        res = U.console_dispatch("check-mail --demo --days 7")
        assert "task_id" in res
        t = _wait_done(res["task_id"])
        assert t["status"] == "done"
    finally:
        G.SEEN_DEFAULT = orig


def test_get_sheet_url(monkeypatch):
    import src.config as C
    monkeypatch.setattr(C, "load_config",
                        lambda **k: type("Cfg", (), {"google_sheet_id": "ABC123"})())
    assert U.get_sheet_url() == "https://docs.google.com/spreadsheets/d/ABC123"


def test_version_handshake():
    assert U.UI_VERSION == 2


def test_spawn_error_includes_trace():
    def boom(task):
        raise RuntimeError("kaput")
    tid = U._spawn("x", boom)
    t = _wait_done(tid)
    assert t["status"] == "error"
    assert "kaput" in t["result"]["error"]
    assert any("RuntimeError" in line for line in t["result"]["trace"])


def _make_job(tmp_path, monkeypatch, name="HP_1", tex="hello tex"):
    import src.utils as UT
    monkeypatch.setattr(UT, "OUTPUT_ROOT", tmp_path)
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    (d / "HP_Resume.tex").write_text(tex, encoding="utf-8")
    return d


def test_get_tex_roundtrip(tmp_path, monkeypatch):
    _make_job(tmp_path, monkeypatch)
    out = U.get_tex("HP_1")
    assert out["file"] == "HP_Resume.tex" and out["content"] == "hello tex"


def test_get_tex_rejects_unknown_and_escape(tmp_path, monkeypatch):
    import src.utils as UT
    monkeypatch.setattr(UT, "OUTPUT_ROOT", tmp_path)
    with pytest.raises(ValueError):
        U.get_tex("Nope_1")
    with pytest.raises(ValueError):
        U.get_tex("../agent")


def test_save_tex_and_compile_success(tmp_path, monkeypatch):
    import src.compiler as Cp
    d = _make_job(tmp_path, monkeypatch)
    pdf = d / "HP_Resume.pdf"
    monkeypatch.setattr(Cp, "compile_tex", lambda tex: (pdf.write_bytes(b"%PDF"), pdf)[1])
    res = U.save_tex("HP_1", "new content", compile_pdf=True)
    assert res["ok"] and res["compiled"]
    assert res["pdf_url"].endswith("HP_Resume.pdf")
    assert (d / "HP_Resume.tex").read_text(encoding="utf-8") == "new content"


def test_save_tex_compile_failure_keeps_tex(tmp_path, monkeypatch):
    import src.compiler as Cp
    d = _make_job(tmp_path, monkeypatch)
    def boom(tex):
        raise Cp.LatexCompileError("tectonic failed", log="! missing }")
    monkeypatch.setattr(Cp, "compile_tex", boom)
    res = U.save_tex("HP_1", "broken tex", compile_pdf=True)
    assert res["ok"] is False and "missing" in res["compile_log"]
    assert (d / "HP_Resume.tex").read_text(encoding="utf-8") == "broken tex"


def test_save_tex_rejects_empty(tmp_path, monkeypatch):
    _make_job(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="empty"):
        U.save_tex("HP_1", "   ")


def test_save_tex_creates_dated_file_when_missing(tmp_path, monkeypatch):
    import re
    import src.utils as UT
    monkeypatch.setattr(UT, "OUTPUT_ROOT", tmp_path)
    (tmp_path / "HP_1").mkdir()
    res = U.save_tex("HP_1", "fresh", compile_pdf=False)
    assert res["ok"] and res["compiled"] is False
    assert re.search(r"_Resume_\d{6}\.tex$", res["file"])


def test_get_sheet_url_empty_when_unconfigured(monkeypatch):
    import src.config as C
    def boom(**k):
        raise C.ConfigError("missing")
    monkeypatch.setattr(C, "load_config", boom)
    assert U.get_sheet_url() == ""
