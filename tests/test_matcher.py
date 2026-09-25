"""Part 2 tests: matcher schema/clamp/fences/empty + resume fallback."""
from __future__ import annotations

import pytest

import src.matcher as M
from src import llm


def _mock_complete(return_value):
    return lambda *a, **k: return_value


def test_match_schema(monkeypatch):
    monkeypatch.setattr(llm, "complete_json", _mock_complete({
        "match_score": 78, "matching_skills": ["python"],
        "missing_skills": ["k8s"], "core_requirements": ["python"]}))
    m = M.analyze_match("Python role needing python", "resume python", api_key="x")
    assert 0 <= m.match_score <= 100
    assert m.matching_skills == ["python"]


def test_match_clamps_score(monkeypatch):
    monkeypatch.setattr(llm, "complete_json", _mock_complete({
        "match_score": 150, "matching_skills": [], "missing_skills": [], "core_requirements": []}))
    assert M.analyze_match("jd", "resume", api_key="x").match_score == 100
    monkeypatch.setattr(llm, "complete_json", _mock_complete({
        "match_score": -5, "matching_skills": [], "missing_skills": [], "core_requirements": []}))
    assert M.analyze_match("jd", "resume", api_key="x").match_score == 0


def test_llm_strips_fences():
    raw = '```json\n{"a": 1}\n``` trailing prose'
    assert llm._extract_json(raw) == {"a": 1}


def test_match_empty_jd_raises():
    with pytest.raises(ValueError):
        M.analyze_match("", "resume", api_key="x")


def test_resume_read_fallback_to_sample():
    text, path = M.read_base_resume()
    assert "documentclass" in text
    assert path.exists()


def test_match_includes_profile(monkeypatch):
    seen = {}
    def fake(prompt, api_key="", model="", **k):
        seen["prompt"] = prompt
        return {"match_score": 80, "matching_skills": ["python", "aws"],
                "missing_skills": [], "core_requirements": ["python"],
                "profile_skills": ["aws"]}
    monkeypatch.setattr(llm, "complete_json", fake)
    m = M.analyze_match("need python aws", "resume python", api_key="x",
                        profile_text="AWS certified")
    assert "AWS certified" in seen["prompt"]
    assert m.profile_skills == ["aws"]
    assert "via LinkedIn: aws" in M.summary_line(m)


def test_match_handles_garbage_score(monkeypatch):
    monkeypatch.setattr(llm, "complete_json", _mock_complete({
        "match_score": "high", "matching_skills": "notalist",
        "missing_skills": [], "core_requirements": []}))
    m = M.analyze_match("jd", "resume", api_key="x")
    assert m.match_score == 0
    assert m.matching_skills == []
