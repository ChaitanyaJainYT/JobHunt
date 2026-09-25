"""profile.py tests: file parse, public parse, graceful failure, merge."""
from __future__ import annotations

import src.profile as Pr


def test_parse_skills_variants():
    assert Pr.parse_skills_block("Python, SQL\n- AWS\n1. Docker") == \
        ["Python", "SQL", "AWS", "Docker"]
    assert Pr.parse_skills_block("Python, python, PYTHON") == ["Python"]


def test_load_local_profile(tmp_path, monkeypatch):
    import src.utils as UT
    monkeypatch.setattr(UT, "PROJECT_ROOT", tmp_path)
    (tmp_path / "profile.md").write_text(
        "# Me\n## About\nI build pipelines.\n## Technical Skills\nPython, SQL\n- AWS\n",
        encoding="utf-8")
    text, skills = Pr.load_local_profile("profile.md")
    assert "pipelines" in text
    assert skills == ["Python", "SQL", "AWS"]
    assert Pr.load_local_profile("missing.md") == ("", [])


def test_fetch_public_profile_parses(tmp_path, monkeypatch):
    import requests
    html = ('<html><head><meta property="og:title" content="Jane Doe">'
            '<meta name="description" content="Data engineer at Acme"></head><body>'
            '<div class="topcard__headlineextra">Wrong</div>'
            '<script>{"skillName":"Python"},{"skillName":"SQL"}</script>'
            "</body></html>")
    class R:
        status_code = 200
        text = html
    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    info = Pr.fetch_public_profile("https://www.linkedin.com/in/jane")
    assert info["name"] == "Jane Doe"
    assert "Data engineer" in info["about"]
    assert info["skills"] == ["Python", "SQL"]


def test_fetch_graceful_on_wall_and_network(monkeypatch):
    import requests
    class R:
        status_code = 999
        text = ""
    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    assert Pr.fetch_public_profile("https://x") == {}
    def boom(*a, **k):
        raise requests.ConnectionError()
    monkeypatch.setattr(requests, "get", boom)
    assert Pr.fetch_public_profile("https://x") == {}
    assert Pr.fetch_public_profile("https://x") == {}


def test_merge_file_and_url(tmp_path, monkeypatch):
    import requests
    import src.utils as UT
    monkeypatch.setattr(UT, "PROJECT_ROOT", tmp_path)
    (tmp_path / "profile.md").write_text("## Skills\nPython\n", encoding="utf-8")
    class R:
        status_code = 200
        text = ('<meta property="og:title" content="Jane">'
                '<script>{"skillName":"SQL"}</script>')
    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    prof = Pr.get_candidate_context("https://www.linkedin.com/in/jane", "profile.md")
    assert prof.source == "file+url"
    assert prof.skills == ["Python", "SQL"]
    assert "Jane" in prof.text


def test_context_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("nope")
    monkeypatch.setattr(Pr, "load_local_profile", boom)
    prof = Pr.get_candidate_context("https://x", "y")
    assert prof.source == "none" and prof.skills == []
