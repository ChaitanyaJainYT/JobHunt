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
    assert U.UI_VERSION >= 3


def test_frontend_backend_version_sync():
    """ui.html must check the exact UI_VERSION, or stale servers slip through."""
    from pathlib import Path
    html = (Path(U.__file__).resolve().parent / "ui.html").read_text(encoding="utf-8")
    assert f"version !== {U.UI_VERSION}" in html


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


def test_search_rejects_empty_query():
    with pytest.raises(ValueError, match="keywords"):
        U.search_jobs_api("  ")


def test_search_normalizes_results(monkeypatch):
    import src.config as C
    import src.job_api as J
    cfg = type("Cfg", (), {"rapidapi_key": "k", "rapidapi_host": "h",
                           "rapidapi_search_endpoint": "e", "rapidapi_country": "in"})()
    monkeypatch.setattr(C, "load_config", lambda **k: cfg)
    items = [{"job_id": "T" * 40, "job_title": "Dev", "employer_name": "Acme",
              "job_description": "x" * 500, "job_location": "Blr"},
             {"job_title": "NoId"}]
    monkeypatch.setattr(J, "search_jobs", lambda *a, **k: items)
    out = U.search_jobs_api("dev", "in")
    assert len(out) == 1  # ID-less item dropped
    assert out[0]["company"] == "Acme" and len(out[0]["snippet"]) == 300


def test_search_linkedin_url_direct_and_fallback(monkeypatch):
    import src.config as C
    import src.job_api as J
    cfg = type("Cfg", (), {"rapidapi_key": "k", "rapidapi_host": "h",
                           "rapidapi_search_endpoint": "e", "rapidapi_country": "in"})()
    monkeypatch.setattr(C, "load_config", lambda **k: cfg)
    items = [
        {"job_id": "T" * 40, "job_title": "Dev", "employer_name": "Acme",
         "job_description": "d",
         "apply_options": [{"publisher": "LinkedIn",
                            "apply_link": "https://www.linkedin.com/jobs/view/123"}]},
        {"job_id": "U" * 40, "job_title": "Data Engineer", "employer_name": "Beta Corp",
         "job_description": "d", "job_apply_link": "https://www.shine.com/jobs/1"},
    ]
    monkeypatch.setattr(J, "search_jobs", lambda *a, **k: items)
    out = U.search_jobs_api("dev", "in")
    assert out[0]["linkedin_url"] == "https://www.linkedin.com/jobs/view/123"
    assert out[0]["linkedin_direct"] is True
    assert out[1]["linkedin_direct"] is False
    assert "linkedin.com/jobs/search" in out[1]["linkedin_url"]
    assert "Data+Engineer" in out[1]["linkedin_url"]


def test_search_config_error_surfaced(monkeypatch):
    import src.config as C
    def boom(**k):
        raise C.ConfigError("missing keys")
    monkeypatch.setattr(C, "load_config", boom)
    with pytest.raises(ValueError, match="missing keys"):
        U.search_jobs_api("dev")


def test_start_apply_accepts_job_id(monkeypatch):
    import src.pipeline as P
    seen = {}
    def fake_run(url, demo=False, resume=False, **k):
        seen["url"] = url
        return 0
    monkeypatch.setattr(P, "run_apply", fake_run)
    tid = U.start_apply_task(job_id="T" * 40)
    t = _wait_done(tid)
    assert t["status"] == "done" and seen["url"] == "T" * 40


def test_start_apply_rejects_garbage():
    with pytest.raises(ValueError):
        U.start_apply_task("hello world")


def test_console_apply_accepts_job_id(monkeypatch):
    monkeypatch.setattr(U, "start_apply_task", lambda *a, **k: "apply-9")
    res = U.console_dispatch("apply " + "T" * 40)
    assert res == {"task_id": "apply-9"}


def test_country_list_sorted_unique_with_gulf():
    import json
    import re
    from pathlib import Path
    import ui as U
    html = (Path(U.__file__).resolve().parent / "ui.html").read_text(encoding="utf-8")
    m = re.search(r"const COUNTRIES = (\[.*?\]);", html, re.DOTALL)
    assert m, "COUNTRIES array not found"
    countries = json.loads(m.group(1))
    names = [n for n, _ in countries]
    codes = [c for _, c in countries]
    assert names == sorted(names), "country names must be A-Z"
    assert len(set(names)) == len(names) and len(set(codes)) == len(codes)
    assert all(re.fullmatch(r"[a-z]{2}", c) for c in codes)
    for code in ("qa", "om", "ae", "sa", "in", "us", "gb"):
        assert code in codes, f"missing country code: {code}"
    assert len(countries) >= 100


def test_resolve_job_dir_by_url_suffix(monkeypatch):
    import time
    jobs = [{"dir": "Acme_99", "updated": time.time() - 100},
            {"dir": "Beta_4242", "updated": time.time() - 100}]
    monkeypatch.setattr(U, "list_jobs", lambda: jobs)
    out = U._resolve_job_dir("https://www.linkedin.com/jobs/view/4242", time.time())
    assert out and out["dir"] == "Beta_4242"


def test_resolve_job_dir_token_uses_freshest(monkeypatch):
    import time
    now = time.time()
    jobs = [{"dir": "Old_1", "updated": now - 3600},
            {"dir": "NewCo_9", "updated": now}]
    monkeypatch.setattr(U, "list_jobs", lambda: jobs)
    out = U._resolve_job_dir("T" * 40, now - 5)
    assert out and out["dir"] == "NewCo_9"
    assert U._resolve_job_dir("T" * 40, now + 100) is None  # nothing newer


def test_persist_task_log(tmp_path, monkeypatch):
    import src.utils as UT
    monkeypatch.setattr(UT, "OUTPUT_ROOT", tmp_path)
    U._persist_task_log({"id": "apply-1", "status": "error", "log": ["line1", "line2"]})
    text = (tmp_path / "ui_tasks.log").read_text(encoding="utf-8")
    assert "apply-1" in text and "line2" in text


def test_base_tex_missing_and_present(tmp_path, monkeypatch):
    import src.utils as UT
    monkeypatch.setattr(UT, "PROJECT_ROOT", tmp_path)
    with pytest.raises(ValueError, match="No main.tex"):
        U.get_base_tex()
    (tmp_path / "main.tex").write_text("base content", encoding="utf-8")
    assert U.get_base_tex()["content"] == "base content"


def test_save_base_writes_backup(tmp_path, monkeypatch):
    import src.utils as UT
    monkeypatch.setattr(UT, "PROJECT_ROOT", tmp_path)
    (tmp_path / "main.tex").write_text("old", encoding="utf-8")
    res = U.save_base_tex("\\documentclass{a}\n\\begin{document}\nnew\n\\end{document}")
    assert res["ok"] and res["backup"] == "main.tex.bak"
    assert (tmp_path / "main.tex").read_text().count("new")
    assert (tmp_path / "main.tex.bak").read_text() == "old"
    with pytest.raises(ValueError, match="empty"):
        U.save_base_tex("  ")
    with pytest.raises(ValueError, match="LaTeX"):
        U.save_base_tex("just prose")


def test_parse_build_helpers():
    tex = "\\documentclass{a}\n\\begin{document}\nHi\n\\section*{S}\nBody\n\\end{document}"
    parsed = U.parse_tex_content(tex)
    assert len(parsed["sections"]) == 2
    out = U.build_tex_content(parsed["head"], parsed["sections"], parsed["tail"])
    assert "\\section*{S}" in out and "Body" in out
    with pytest.raises(ValueError):
        U.parse_tex_content("nope")
    with pytest.raises(ValueError):
        U.build_tex_content("h", [], "t")


def test_render_preview_success_and_failure(tmp_path, monkeypatch):
    import src.compiler as Cp
    import src.utils as UT
    monkeypatch.setattr(UT, "OUTPUT_ROOT", tmp_path)
    pdf = tmp_path / ".preview" / "preview.pdf"
    monkeypatch.setattr(Cp, "compile_tex", lambda tex: (pdf.parent.mkdir(exist_ok=True), pdf.write_bytes(b"%PDF"), pdf)[2])
    res = U.render_preview("\\documentclass{a} x")
    assert res["ok"] and res["pdf_url"].endswith("preview.pdf")

    def boom(tex):
        raise Cp.LatexCompileError("bad tex", log="! oops")
    monkeypatch.setattr(Cp, "compile_tex", boom)
    res = U.render_preview("\\documentclass{a} y")
    assert res["ok"] is False and "oops" in res["compile_log"]
    with pytest.raises(ValueError):
        U.render_preview("  ")


def _seed_job(root, name="HP_1", company="HP"):
    d = root / name
    d.mkdir(exist_ok=True)
    (d / "job.json").write_text(json.dumps({"company": company, "title": "T"}))
    return d


def test_soft_delete_hides_but_keeps_data(tmp_path, monkeypatch):
    import src.utils as UT
    monkeypatch.setattr(UT, "OUTPUT_ROOT", tmp_path)
    _seed_job(tmp_path)
    assert len(U.list_jobs()) == 1
    res = U.soft_delete_job("HP_1")
    assert res["deleted"] is True
    assert U.list_jobs() == []
    full = U.list_jobs(include_deleted=True)
    assert len(full) == 1 and full[0]["deleted"] is True
    # folder + files untouched on disk
    assert (tmp_path / "HP_1" / "job.json").exists()
    res = U.restore_job("HP_1")
    assert res["deleted"] is False
    assert len(U.list_jobs()) == 1


def test_soft_delete_rejects_unknown(tmp_path, monkeypatch):
    import src.utils as UT
    monkeypatch.setattr(UT, "OUTPUT_ROOT", tmp_path)
    with pytest.raises(ValueError):
        U.soft_delete_job("Nope_1")
    with pytest.raises(ValueError):
        U.soft_delete_job("../agent")


def test_tombstone_prunes_missing_dirs(tmp_path, monkeypatch):
    import src.utils as UT
    monkeypatch.setattr(UT, "OUTPUT_ROOT", tmp_path)
    _seed_job(tmp_path, "Gone_1")
    U.soft_delete_job("Gone_1")
    import shutil
    shutil.rmtree(tmp_path / "Gone_1")
    U.restore_job("Other_1")  # any write prunes
    assert U.load_tombstones() == set()


def test_get_sheet_url_empty_when_unconfigured(monkeypatch):
    import src.config as C
    def boom(**k):
        raise C.ConfigError("missing")
    monkeypatch.setattr(C, "load_config", boom)
    assert U.get_sheet_url() == ""
