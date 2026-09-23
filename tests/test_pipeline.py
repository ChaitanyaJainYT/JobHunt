"""Part 6 tests: demo E2E, base-resume preservation, PDF-fail continuity, CLI routing."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import src.pipeline as P
import src.sheets as S
from src.cli import normalize_args
from src.compiler import LatexCompileError
from src.sheets import FakeClient


def _base_hash() -> str | None:
    for cand in [Path("main.tex"), Path("main.tex.sample")]:
        if cand.exists():
            return hashlib.sha256(cand.read_bytes()).hexdigest()
    return None


def test_demo_e2e(tmp_path):
    c = FakeClient()
    rc = P.run_apply("https://www.linkedin.com/jobs/view/4012345678",
                     demo=True, out=str(tmp_path / "job1"), sheet_client=c)
    assert rc == 0
    folder = tmp_path / "job1"
    for f in ["job.json", "match.json", "run.log"]:
        assert (folder / f).exists(), f
    assert list(folder.glob("*_Resume.tex"))
    assert list(folder.glob("*.pdf"))
    vals = c.ws.get_all_values()
    assert vals[0] == S.HEADER and len(vals) == 2


def test_pipeline_preserves_base_resume(tmp_path):
    before = _base_hash()
    P.run_apply("https://www.linkedin.com/jobs/view/1", demo=True,
                out=str(tmp_path / "j2"), sheet_client=FakeClient())
    assert _base_hash() == before


def test_pipeline_continues_on_pdf_fail(tmp_path):
    from src.matcher import MatchResult
    c = FakeClient()
    def boom(*a, **k):
        raise LatexCompileError("tectonic failed", log="bad")
    rc = P.run_apply("https://www.linkedin.com/jobs/view/1", demo=False,
                     out=str(tmp_path / "j3"), sheet_client=c,
                     cfg=type("C", (), {"rapidapi_key": "k", "rapidapi_host": "h",
                                        "rapidapi_job_endpoint": "e", "gemini_api_key": "g",
                                        "groq_api_key": "", "groq_model": "gm",
                                        "llm_model": "m",
                                        "rapidapi_search_endpoint": "https://e/search",
                                        "rapidapi_country": "in",
                                        "google_sheet_id": "demo",
                                        "google_credentials_file": "c"})(),
                     _overrides={
                         "fetch_job": lambda *a, **k: type("J", (), {
                             "title": "T", "company": "Acme", "description": "Python role",
                             "apply_link": "https://apply/1", "job_id": "1"})(),
                         "analyze_match": lambda *a, **k: MatchResult(80, ["python"], [], ["python"]),
                         "tailor_resume": lambda *a, **k: "\\documentclass{article}\n\\begin{document}\nHi\n\\end{document}\n",
                         "compile_with_heal": boom,
                     })
    assert rc == 4  # compile failed but pipeline continued
    vals = c.ws.get_all_values()
    assert len(vals) == 2 and "FAILED" in vals[1][4]  # PDF path col shows FAILED


def test_resume_reuses_saved_artifacts(tmp_path, monkeypatch):
    import json as _json
    import src.pipeline as _P
    from src.matcher import MatchResult
    from src.sheets import FakeClient
    # fake prior run dir: <anything>_<jobid> with job.json + match.json
    prior = tmp_path / "HP_4242"
    prior.mkdir()
    (prior / "job.json").write_text(_json.dumps({
        "title": "T", "company": "HP", "description": "Python role",
        "apply_link": "https://apply/9", "job_id": "4242", "source_url": "u"}))
    (prior / "match.json").write_text(_json.dumps({
        "match_score": 65, "matching_skills": ["python"], "missing_skills": [],
        "core_requirements": ["python"]}))
    import src.utils as U
    monkeypatch.setattr(U, "OUTPUT_ROOT", tmp_path)
    def fail_fetch(*a, **k):
        raise AssertionError("fetch must not be called on --resume")
    def fail_match(*a, **k):
        raise AssertionError("match must not be called on --resume")
    def fake_compile(tex_path, **k):
        pdf = tex_path.with_suffix(".pdf")
        pdf.write_text("pdf", encoding="utf-8")
        return pdf
    c = FakeClient()
    rc = _P.run_apply("https://www.linkedin.com/jobs/view/4242", demo=False,
                      sheet_client=c, resume=True,
                      cfg=type("C", (), {"rapidapi_key": "k", "rapidapi_host": "h",
                                         "rapidapi_job_endpoint": "e", "gemini_api_key": "g",
                                         "groq_api_key": "", "groq_model": "gm",
                                         "llm_model": "m",
                                         "rapidapi_search_endpoint": "https://e/search",
                                         "rapidapi_country": "in",
                                         "google_sheet_id": "demo",
                                         "google_credentials_file": "c"})(),
                      _overrides={
                          "fetch_job": fail_fetch,
                          "analyze_match": fail_match,
                          "tailor_resume": lambda *a, **k: "\\documentclass{article}\n\\begin{document}\nHi\n\\end{document}\n",
                          "compile_with_heal": fake_compile,
                      })
    assert rc == 0
    vals = c.ws.get_all_values()
    assert len(vals) == 2 and vals[1][1] == "HP"


def test_cli_routing():
    ns = normalize_args(["apply", "--url", "https://www.linkedin.com/jobs/view/99"])
    assert ns.command == "apply" and ns.url.endswith("/99")
    ns = normalize_args(["--check-mail"])
    assert ns.command == "check-mail"


def test_demo_check_mail_flow(tmp_path):
    rc = P.run_check_mail_flow(days=7, demo=True, sheet_client=FakeClient(),
                               seen_path=tmp_path / "seen.json")
    assert rc == 0
