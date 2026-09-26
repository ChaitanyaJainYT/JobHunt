"""md2latex tests: inline, blocks, lists, escaping, detection."""
from __future__ import annotations

from src.md2latex import convert, detect_format, escape_tex, md_to_latex


def test_escape_specials_once():
    assert escape_tex("R&D 100% $x_2 {a} ~ ^ \\") == \
        "R\\&D 100\\% \\$x\\_2 \\{a\\} \\textasciitilde{} \\textasciicircum{} \\textbackslash{}"


def test_inline_bold_italic_code_link():
    assert "\\textbf{a}" in md_to_latex("**a**")
    assert "\\textit{b}" in md_to_latex("*b*")
    assert "\\textbf{\\textit{c}}" in md_to_latex("***c***")
    assert "\\texttt{x}" in md_to_latex("`x`")
    assert "Site (https://e.com/a\\_b)" in md_to_latex("[Site](https://e.com/a_b)")
    # snake_case untouched
    assert "my\\_var" in md_to_latex("my_var")


def test_bullet_and_numbered_lists():
    out = md_to_latex("- a\n- b")
    assert "\\begin{itemize}" in out and "\\item a" in out and "\\end{itemize}" in out
    out = md_to_latex("1. one\n2. two")
    assert "\\begin{enumerate}" in out and "\\item two" in out


def test_nested_list():
    out = md_to_latex("- top\n  - sub\n- next")
    assert out.count("\\begin{itemize}") == 2 and "\\item sub" in out


def test_paragraphs_and_hard_break():
    out = md_to_latex("line one  \nline two\n\npara two")
    assert "\\\\" in out and "para two" in out


def test_markup_inside_items_and_escaping():
    out = md_to_latex("- 100% **faster** & safer")
    assert "\\item 100\\% \\textbf{faster} \\& safer" in out


def test_convert_dispatch_and_passthrough():
    assert convert("x & y", "plain") == "x \\& y"
    assert convert("\\textbf{x}", "latex") == "\\textbf{x}"
    assert convert("a\nb", "plain") == "a \\\\\nb"


def test_detect_format():
    assert detect_format("\\section*{S}\n\\item x") == "latex"
    assert detect_format("{\\Large Jane} \\\\ dev@example.com") == "latex"
    assert detect_format("line one \\\\ line two") == "latex"
    assert detect_format("- a\n- b") == "markdown"
    assert detect_format("**bold** move") == "markdown"
    assert detect_format("Jane Doe\ndev@example.com") == "plain"


def test_latex_bodies_roundtrip_verbatim():
    from src.resume_model import build_resume, parse_resume
    tex = ("\\documentclass{a}\n\\begin{document}\n{\\Large Jane} \\\\ mail\n"
           "\\section*{S}\nA \\textbf{B} \\& C\n\\end{document}")
    p = parse_resume(tex)
    assert all(s.format == "latex" for s in p.sections)
    out = build_resume(p.head, p.sections, p.tail)
    assert "{\\Large Jane} \\\\" in out and "A \\textbf{B} \\& C" in out
