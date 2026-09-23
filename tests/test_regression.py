"""Regression tests: LLM transient retry + OAuth denied hint."""
from __future__ import annotations

from src import llm
from src.sheets import oauth_denied_hint


def test_complete_json_retries_transient_504(monkeypatch):
    calls = {"n": 0}
    def fake_call(prompt, api_key, model, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise Exception("504 Deadline expired before operation could complete.")
        return '{"match_score": 70}'
    monkeypatch.setattr(llm, "_call_gemini", fake_call)
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)
    out = llm.complete_json("p", api_key="x")
    assert out == {"match_score": 70}
    assert calls["n"] == 2


def test_complete_json_no_retry_on_bad_key(monkeypatch):
    calls = {"n": 0}
    def fake_call(prompt, api_key, model, timeout):
        calls["n"] += 1
        raise Exception("400 API key not valid [API_KEY_INVALID]")
    monkeypatch.setattr(llm, "_call_gemini", fake_call)
    try:
        llm.complete_json("p", api_key="bad")
        assert False, "should raise"
    except llm.LLMError as e:
        assert "rejected" in str(e)
    assert calls["n"] == 1


def test_complete_text_retries_transient(monkeypatch):
    calls = {"n": 0}
    def fake_call(prompt, api_key, model, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise Exception("503 Service Unavailable")
        return "\\documentclass{article}"
    monkeypatch.setattr(llm, "_call_gemini", fake_call)
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)
    assert "documentclass" in llm.complete_text("p", api_key="x")
    assert calls["n"] == 2


def test_oauth_denied_hint_triggers():
    hint = oauth_denied_hint("(access_denied) User denied")
    assert "Test users" in hint and "Audience" in hint


def test_oauth_denied_hint_empty_for_other_errors():
    assert oauth_denied_hint("connection refused") == ""


def test_groq_fallback_on_gemini_quota(monkeypatch):
    calls = []
    def fake_gemini(prompt, api_key, model, timeout):
        calls.append("gemini")
        raise Exception("429 You exceeded your current quota")
    def fake_groq(prompt, groq_key, model="openai/gpt-oss-120b"):
        calls.append(("groq", model))
        return '{"match_score": 66}'
    monkeypatch.setattr(llm, "_call_gemini", fake_gemini)
    monkeypatch.setattr(llm, "_call_groq", fake_groq)
    out = llm.complete_json("p", api_key="g", groq_key="q")
    assert out == {"match_score": 66}
    assert calls[0] == "gemini" and calls[1][0] == "groq"


def test_no_groq_fallback_without_key(monkeypatch):
    def fake_gemini(prompt, api_key, model, timeout):
        raise Exception("429 quota exceeded")
    monkeypatch.setattr(llm, "_call_gemini", fake_gemini)
    try:
        llm.complete_text("p", api_key="g")
        assert False, "should raise"
    except llm.LLMError as e:
        assert "quota" in str(e).lower()
