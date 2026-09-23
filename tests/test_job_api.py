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


def test_public_login_wall_raises(monkeypatch):
    import src.job_api as J
    class R:
        status_code = 200
        text = "<html><body>login wall</body></html>"
    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    with pytest.raises(JobFetchError, match="no readable job data"):
        J.fetch_linkedin_public("https://www.linkedin.com/jobs/view/111")
