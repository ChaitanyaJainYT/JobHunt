"""resume_model tests: parse/build fidelity + error paths."""
from __future__ import annotations

import pytest

from src.resume_model import Section, build_resume, parse_resume

TEX = (
    "\\documentclass{article}\n\\usepackage{x}\n"
    "\\begin{document}\n"
    "{\\Large Jane} \\\\ dev@example.com\n"
    "\\section*{Skills}\nPython, SQL\n"
    "\\section{Experience}\nDid things.\n"
    "\\end{document}\n"
)


def test_parse_sections_starred_and_plain():
    p = parse_resume(TEX)
    assert "\\documentclass" in p.head and "\\begin{document}" in p.head
    assert len(p.sections) == 3
    pre, skills, exp = p.sections
    assert pre.title is None and "Jane" in pre.body
    assert (skills.title, skills.starred) == ("Skills", True)
    assert "Python" in skills.body
    assert (exp.title, exp.starred) == ("Experience", False)


def test_roundtrip_preserves_head_and_content():
    p = parse_resume(TEX)
    out = build_resume(p.head, p.sections, p.tail)
    assert "\\usepackage{x}" in out
    assert out.count("\\section*{Skills}") == 1
    assert "Did things." in out
    assert out.rstrip().endswith("\\end{document}")


def test_build_applies_edits_and_order():
    p = parse_resume(TEX)
    p.sections[1].body = "Python, SQL, Rust"
    p.sections.append(Section("Projects", True, "Built stuff."))
    out = build_resume(p.head, p.sections, p.tail)
    assert "Rust" in out and "Projects" in out
    assert out.index("Skills") < out.index("Projects")


def test_no_sections_is_single_preamble():
    p = parse_resume("\\documentclass{a}\n\\begin{document}\nJust text.\n\\end{document}")
    assert len(p.sections) == 1 and p.sections[0].title is None


def test_invalid_docs_raise():
    with pytest.raises(ValueError):
        parse_resume("hello")
    with pytest.raises(ValueError):
        parse_resume("\\documentclass{a}\nno body here")


def test_empty_titles_skipped():
    out = build_resume("\\documentclass{a}\n\\begin{document}",
                       [Section("", True, "x"), Section("Real", True, "y")])
    assert "Real" in out and "{}\n" not in out
