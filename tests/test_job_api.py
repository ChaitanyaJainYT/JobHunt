"""Part 1 tests: URL parsing + RapidAPI fetch (all mocked)."""
from __future__ import annotations

import pytest
import requests

from src.job_api import (
    JobFetchError,
    JobURLError,
    fetch_job,
    parse_job_id,
)


def test_parse_linkedin_view_url():
    assert parse_job_id("https://www.linkedin.com/jobs/view/4012345678") == "4012345678"


def test_parse_linkedin_search_url():
    url = "https://www.linkedin.com/jobs/search/?currentJobId=4012345678&keywords=python"
    assert parse_job_id(url) == "4012345678"


def test_invalid_url_raises():
    with pytest.raises(JobURLError):
        parse_job_id("https://google.com")


def _resp(status=200, payload=None, text=""):
    class R:
        status_code = status
        def json(self):
            if payload is None:
                raise ValueError("no json")
            return payload
        @property
        def text(self):
            return text or str(payload)
    return R()


def test_fetch_normalizes_fields(monkeypatch):
    payload = {"data": [{
        "job_title": "Backend Dev",
        "employer_name": "Acme",
        "job_description": "Python role",
        "job_apply_link": "https://apply.here/1",
    }]}
    monkeypatch.setattr(requests, "get", lambda *a, **k: _resp(200, payload))
    job = fetch_job("https://www.linkedin.com/jobs/view/111", "k", "h", "https://e")
    assert job.title == "Backend Dev"
    assert job.company == "Acme"
    assert job.apply_link == "https://apply.here/1"
    assert job.job_id == "111"


def test_fetch_401_message(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _resp(401, {}, "unauthorized"))
    with pytest.raises(JobFetchError, match="RAPIDAPI_KEY"):
        fetch_job("https://www.linkedin.com/jobs/view/111", "bad", "h", "https://e")


def test_fetch_timeout(monkeypatch):
    def boom(*a, **k):
        raise requests.Timeout()
    monkeypatch.setattr(requests, "get", boom)
    with pytest.raises(JobFetchError, match="--demo"):
        fetch_job("https://www.linkedin.com/jobs/view/111", "k", "h", "https://e")


def test_fetch_empty_description_raises(monkeypatch):
    payload = {"data": {"job_title": "T", "employer_name": "C"}}
    monkeypatch.setattr(requests, "get", lambda *a, **k: _resp(200, payload))
    with pytest.raises(JobFetchError, match="empty job description"):
        fetch_job("https://www.linkedin.com/jobs/view/111", "k", "h", "https://e")


def test_public_fallback_parses_page(monkeypatch):
    from pathlib import Path
    import src.job_api as J
    html = (Path(__file__).parent / "fixtures" / "sample_linkedin_public.html").read_text(encoding="utf-8")
    class R:
        status_code = 200
        text = html
    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    job = J.fetch_linkedin_public("https://www.linkedin.com/jobs/view/4012345678")
    assert job.title == "Data Engineer(Python/AWS/SQL)"
    assert job.company == "LSEG"
    assert "Python" in job.description and "data pipelines" in job.description
    assert job.job_id == "4012345678"


def test_auto_falls_back_when_api_empty(monkeypatch):
    import src.job_api as J
    from pathlib import Path
    html = (Path(__file__).parent / "fixtures" / "sample_linkedin_public.html").read_text(encoding="utf-8")
    class R:
        def __init__(self, status=200, payload=None, text=""):
            self.status_code = status
            self._payload = payload
            self.text = text or str(payload)
        def json(self):
            return self._payload
    def fake_get(url, **k):
        if url == "https://e":
            return R(200, {"data": {}})
        return R(200, None, html)
    monkeypatch.setattr(requests, "get", fake_get)
    job = J.fetch_job_auto("https://www.linkedin.com/jobs/view/4012345678", "k", "h", "https://e")
    assert job.company == "LSEG"


def test_backend_error_envelope_surfaced(monkeypatch):
    payload = {"status": "ERROR", "request_id": "abc",
               "error": {"message": "Missing query", "code": 400}}
    monkeypatch.setattr(requests, "get", lambda *a, **k: _resp(200, payload))
    with pytest.raises(JobFetchError, match="Missing query"):
        fetch_job("https://www.linkedin.com/jobs/view/111", "k", "h", "https://e")


def test_public_skips_signup_apply_link(monkeypatch):
    import src.job_api as J
    html = ('<html><body>'
            '<h1 class="topcard__title">T</h1>'
            '<a class="topcard__org-name-link" href="https://linkedin.com/company/c">C</a>'
            '<a href="https://www.linkedin.com/signup/cold-join?source=x" '
            'data-tracking-control-name="public_jobs_apply-link-offsite">Apply</a>'
            '<div class="description__text"><div class="show-more-less-html__markup">Real work here.</div></div>'
            '</body></html>')
    class R:
        status_code = 200
        text = html
    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    job = J.fetch_linkedin_public("https://www.linkedin.com/jobs/view/999")
    assert job.apply_link == "https://www.linkedin.com/jobs/view/999"


def test_auto_linkedin_path_tries_search_then_public(monkeypatch):
    import src.job_api as J
    from pathlib import Path
    html = (Path(__file__).parent / "fixtures" / "sample_linkedin_public.html").read_text(encoding="utf-8")
    calls = []
    class R:
        status_code = 200
        text = html
    def fake_get(url, **k):
        calls.append(url)
        if "linkedin.com" in url:
            return R()
        # search returns nothing confident -> public data kept
        return _resp(200, _search_payload([]))
    monkeypatch.setattr(requests, "get", fake_get)
    job = J.fetch_job_auto("https://www.linkedin.com/jobs/view/4012345678",
                           "k", "jsearch.p.rapidapi.com", "https://jsearch.p.rapidapi.com/job-details")
    assert job.company == "LSEG"
    assert len(calls) == 2 and "linkedin.com" in calls[0] and "search-v2" in calls[1]
    assert "job-details" not in " ".join(calls)  # no blind details call with LinkedIn ID


def test_auto_uses_rapidapi_for_linkedin_host(monkeypatch):
    import src.job_api as J
    payload = {"data": {"job_title": "T", "employer_name": "C", "job_description": "D"}}
    seen = []
    def fake_get(url, **k):
        seen.append(url)
        return _resp(200, payload)
    monkeypatch.setattr(requests, "get", fake_get)
    job = J.fetch_job_auto("https://www.linkedin.com/jobs/view/4012345678",
                           "k", "linkedin-jobs-api.p.rapidapi.com", "https://e/job-details")
    assert job.title == "T"
    assert seen and "linkedin.com/jobs" not in seen[0]


def _search_payload(jobs):
    return {"status": "OK", "data": {"jobs": jobs, "cursor": None}}


def test_search_unwraps_jobs_dict(monkeypatch):
    import src.job_api as J
    jobs = [{"job_id": "TOK1", "job_title": "Data Engineer", "employer_name": "LSEG",
             "job_description": "Python pipelines", "job_apply_link": "https://apply/1"}]
    monkeypatch.setattr(requests, "get", lambda *a, **k: _resp(200, _search_payload(jobs)))
    out = J.search_jobs("Data Engineer LSEG", "k", "h", "https://e/search-v2", "in")
    assert len(out) == 1 and out[0]["job_id"] == "TOK1"


def test_search_retries_once_on_timeout(monkeypatch):
    import src.job_api as J
    calls = {"n": 0}
    jobs = [{"job_id": "T1", "job_title": "Dev"}]
    def fake_get(url, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.Timeout()
        return _resp(200, _search_payload(jobs))
    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(J.time, "sleep", lambda *_: None)
    out = J.search_jobs("dev", "k", "h", "https://e/search-v2")
    assert len(out) == 1 and calls["n"] == 2


def test_search_double_timeout_friendly(monkeypatch):
    import src.job_api as J
    def boom(*a, **k):
        raise requests.Timeout()
    monkeypatch.setattr(requests, "get", boom)
    monkeypatch.setattr(J.time, "sleep", lambda *_: None)
    with pytest.raises(JobFetchError, match="timed out twice"):
        J.search_jobs("dev", "k", "h", "https://e/search-v2")


def test_search_backend_error_surfaced(monkeypatch):
    import src.job_api as J
    payload = {"status": "ERROR", "error": {"message": "Invalid date posted value.", "code": 400}}
    monkeypatch.setattr(requests, "get", lambda *a, **k: _resp(200, payload))
    with pytest.raises(JobFetchError, match="Invalid date posted"):
        J.search_jobs("x", "k", "h", "https://e/search-v2")


def test_enrich_picks_company_match_and_keeps_linkedin_id(monkeypatch):
    import src.job_api as J
    public = J.Job("Data Engineer", "LSEG", "public desc", "https://linkedin.com/jobs/view/99",
                   "99", "https://linkedin.com/jobs/view/99")
    jobs = [
        {"job_id": "WRONG", "job_title": "Barista", "employer_name": "Cafe",
         "job_description": "coffee", "job_apply_link": "https://x/1"},
        {"job_id": "RIGHT", "job_title": "Senior Data Engineer", "employer_name": "LSEG",
         "job_description": "rich desc", "job_apply_link": "https://shine.com/apply/9"},
    ]
    details = {"data": {"job_title": "Senior Data Engineer", "employer_name": "LSEG",
                        "job_description": "rich desc", "job_apply_link": "https://shine.com/apply/9"}}
    def fake_get(url, **k):
        if "search-v2" in url:
            return _resp(200, _search_payload(jobs))
        return _resp(200, details)
    monkeypatch.setattr(requests, "get", fake_get)
    rich = J.enrich_via_search(public, "k", "h", "https://e/job-details", "https://e/search-v2")
    assert rich.description == "rich desc"
    assert rich.job_id == "99"  # LinkedIn ID preserved for folders/resume
    assert "shine.com" in rich.apply_link


def test_enrich_rejects_title_only_match(monkeypatch):
    # Regression: "Data Engineer @ TailorFlow" must NOT attach to an HP posting
    # even though title tokens overlap 100%.
    import src.job_api as J
    public = J.Job("Data Engineer", "HP", "public desc", "u", "99", "u")
    jobs = [{"job_id": "X", "job_title": "Data Engineer AI Applications",
             "employer_name": "TailorFlow AI", "job_description": "wrong company"}]
    monkeypatch.setattr(requests, "get", lambda *a, **k: _resp(200, _search_payload(jobs)))
    assert J.enrich_via_search(public, "k", "h", "https://e/job-details", "https://e/search-v2") is None


def test_enrich_accepts_company_variants(monkeypatch):
    import src.job_api as J
    assert J._company_hit("HP", "HP Inc.")
    assert J._company_hit("LSEG", "LSEG")
    assert not J._company_hit("HP", "TailorFlow AI")
    assert not J._company_hit("", "HP")


def test_enrich_returns_none_without_confident_match(monkeypatch):
    import src.job_api as J
    public = J.Job("Data Engineer", "LSEG", "public desc", "u", "99", "u")
    jobs = [{"job_id": "X", "job_title": "Barista", "employer_name": "Cafe",
             "job_description": "coffee"}]
    monkeypatch.setattr(requests, "get", lambda *a, **k: _resp(200, _search_payload(jobs)))
    assert J.enrich_via_search(public, "k", "h", "https://e/job-details", "https://e/search-v2") is None


def test_auto_linkedin_path_enriches(monkeypatch):
    import src.job_api as J
    from pathlib import Path
    html = (Path(__file__).parent / "fixtures" / "sample_linkedin_public.html").read_text(encoding="utf-8")
    jobs = [{"job_id": "T1", "job_title": "Data Engineer", "employer_name": "LSEG",
             "job_description": "rich", "job_apply_link": "https://apply/1"}]
    details = {"data": {"job_title": "Data Engineer", "employer_name": "LSEG",
                        "job_description": "rich", "job_apply_link": "https://apply/1"}}
    class R:
        status_code = 200
        text = html
    def fake_get(url, **k):
        if "linkedin.com" in url:
            return R()
        if "search-v2" in url:
            return _resp(200, _search_payload(jobs))
        return _resp(200, details)
    monkeypatch.setattr(requests, "get", fake_get)
    job = J.fetch_job_auto("https://www.linkedin.com/jobs/view/4012345678", "k",
                           "jsearch.p.rapidapi.com", "https://e/job-details")
    assert job.description == "rich" and job.job_id == "4012345678"


def test_public_login_wall_raises(monkeypatch):
    import src.job_api as J
    class R:
        status_code = 200
        text = "<html><body>login wall</body></html>"
    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    with pytest.raises(JobFetchError, match="no readable job data"):
        J.fetch_linkedin_public("https://www.linkedin.com/jobs/view/111")
