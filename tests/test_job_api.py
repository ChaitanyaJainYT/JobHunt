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
