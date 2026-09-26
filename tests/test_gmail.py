"""Part 5 tests: gmail classify/update/seen/spam/truncate (mocked)."""
from __future__ import annotations

from pathlib import Path

import src.gmail as G
import src.sheets as S
from src import llm
from src.sheets import FakeClient


def _fetcher_factory(emails):
    def fetch(company):
        return [e for e in emails if e.company == company]
    return fetch


def test_rejection_classified(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {"label": "Rejection", "confidence": 0.9})
    ws_client = FakeClient()
    ws_client.ws.rows = [S.HEADER, ["2026-09-01", "Acme Corp", "T", "80", "p", "u", "Applied", ""]]
    emails = [G.Email("m1", "Acme Corp", "Update", "2026-09-20", "we will not be moving forward")]
    res = G.run_check_mail(["Acme Corp"], "demo", days=7, api_key="x",
                           seen_path=tmp_path / "seen.json",
                           email_fetcher=_fetcher_factory(emails), sheet_client=ws_client)
    assert res[0]["label"] == "Rejection" and res[0]["updated"] is True
    assert ws_client.ws.rows[1][6] == "Rejection"


def test_interview_classified(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {"label": "Interview Invite", "confidence": 0.95})
    ws_client = FakeClient()
    ws_client.ws.rows = [S.HEADER, ["2026-09-01", "Acme Corp", "T", "80", "p", "u", "Applied", ""]]
    emails = [G.Email("m2", "Acme Corp", "Invite", "2026-09-21", "invite you to interview")]
    res = G.run_check_mail(["Acme Corp"], "demo", api_key="x",
                           seen_path=tmp_path / "seen.json",
                           email_fetcher=_fetcher_factory(emails), sheet_client=ws_client)
    assert res[0]["label"] == "Interview Invite"


def test_spam_skipped(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {"label": "Marketing/Spam", "confidence": 0.99})
    ws_client = FakeClient()
    ws_client.ws.rows = [S.HEADER, ["2026-09-01", "SpamCo", "T", "10", "p", "u", "Applied", ""]]
    emails = [G.Email("m3", "SpamCo", "50% off", "2026-09-22", "buy courses")]
    res = G.run_check_mail(["SpamCo"], "demo", api_key="x",
                           seen_path=tmp_path / "seen.json",
                           email_fetcher=_fetcher_factory(emails), sheet_client=ws_client)
    assert res[0]["updated"] is False
    assert ws_client.ws.rows[1][6] == "Applied"


def test_seen_ids_skipped(monkeypatch, tmp_path):
    calls = {"n": 0}
    def fake_llm(*a, **k):
        calls["n"] += 1
        return {"label": "Rejection", "confidence": 0.9}
    monkeypatch.setattr(llm, "complete_json", fake_llm)
    seen = tmp_path / "seen.json"
    emails = [G.Email("m1", "Acme Corp", "S", "D", "b")]
    ws_client = FakeClient()
    ws_client.ws.rows = [S.HEADER, ["d", "Acme Corp", "T", "1", "p", "u", "Applied", ""]]
    G.run_check_mail(["Acme Corp"], "demo", api_key="x", seen_path=seen,
                     email_fetcher=_fetcher_factory(emails), sheet_client=ws_client)
    G.run_check_mail(["Acme Corp"], "demo", api_key="x", seen_path=seen,
                     email_fetcher=_fetcher_factory(emails), sheet_client=ws_client)
    assert calls["n"] == 1  # second run skipped via seen


def test_truncates_long_body(monkeypatch):
    captured = {}
    def fake(prompt, api_key="", model="", groq_key="", **_k):
        captured["len"] = len(prompt)
        return {"label": "Other", "confidence": 0.5}
    monkeypatch.setattr(llm, "complete_json", fake)
    G.classify_email("s", "x" * 50000, api_key="x")
    assert captured["len"] < 8000


def test_no_companies_no_crash(tmp_path):
    assert G.run_check_mail([], "demo", seen_path=tmp_path / "s.json") == []


def test_sync_local_job_status(tmp_path, monkeypatch):
    import json as _json
    import src.utils as UT
    monkeypatch.setattr(UT, "OUTPUT_ROOT", tmp_path)
    d1 = tmp_path / "Acme_old"
    d1.mkdir()
    (d1 / "job.json").write_text(_json.dumps({"company": "Acme Corp", "title": "T"}))
    import time
    d2 = tmp_path / "Acme_new"
    d2.mkdir()
    (d2 / "job.json").write_text(_json.dumps({"company": "ACME corp", "title": "T2"}))
    assert G.sync_local_job_status("acme CORP", "Interview Invite") is True
    assert _json.loads((d2 / "job.json").read_text())["status"] == "Interview Invite"
    assert "status" not in _json.loads((d1 / "job.json").read_text())  # latest only
    assert G.sync_local_job_status("Nobody", "Offer") is False


def test_sync_never_raises(tmp_path, monkeypatch):
    import src.utils as UT
    monkeypatch.setattr(UT, "OUTPUT_ROOT", tmp_path / "missing")
    assert G.sync_local_job_status("Acme", "Offer") is False


def test_low_confidence_skipped(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {"label": "Offer", "confidence": 0.4})
    ws_client = FakeClient()
    ws_client.ws.rows = [S.HEADER, ["d", "Acme Corp", "T", "1", "p", "u", "Applied", ""]]
    emails = [G.Email("m9", "Acme Corp", "S", "D", "b")]
    res = G.run_check_mail(["Acme Corp"], "demo", api_key="x", seen_path=tmp_path / "s.json",
                           email_fetcher=_fetcher_factory(emails), sheet_client=ws_client)
    assert res[0]["updated"] is False
