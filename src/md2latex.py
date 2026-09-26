"""Plain-text / Markdown -> LaTeX for the sections editor. Stdlib only.

Formats:
- "latex": passthrough (current behavior).
- "plain": escape special chars; blank line = paragraph; single newline = \\\\.
- "markdown": paragraphs, **bold**, *italic*, `code`, [text](url) as
  "text (url)", -/* unordered and 1. ordered lists (one nesting level),
  # heading -> bold line. Tables/images/hr degrade to plain paragraphs.

Only base-LaTeX commands are emitted (itemize/enumerate/textbf/textit/
texttt/medskip) so no extra packages are ever required.
"""
from __future__ import annotations

import re

_P0 = "\x00"  # code span slot
_P1 = "\x01"  # link slot
_P2 = "\x02"  # emphasis slot


def escape_tex(s: str) -> str:
    out = s.replace("\\", _P0 + "BS" + _P0)
    for a, b in [("&", "\\&"), ("%", "\\%"), ("$", "\\$"), ("#", "\\#"),
                 ("_", "\\_"), ("{", "\\{"), ("}", "\\}"),
                 ("~", "\\textasciitilde{}"), ("^", "\\textasciicircum{}")]:
        out = out.replace(a, b)
    return out.replace(_P0 + "BS" + _P0, "\\textbackslash{}")


def _inline(text: str) -> str:
    codes: list[str] = []
    links: list[tuple[str, str]] = []
    emphs: list[tuple[str, str]] = []

    def stash_code(m):
        codes.append(m.group(1))
        return f"{_P0}{len(codes) - 1}{_P0}"

    def stash_link(m):
        links.append((m.group(1), m.group(2)))
        return f"{_P1}{len(links) - 1}{_P1}"

    def stash_emph(kind):
        def _f(m):
            emphs.append((kind, m.group(1)))
            return f"{_P2}{len(emphs) - 1}{_P2}"
        return _f

    t = re.sub(r"`([^`\n]+)`", stash_code, text)
    t = re.sub(r"!\[([^\]\n]*)\]\(([^)\s]+)\)", stash_link, t)  # image -> like link
    t = re.sub(r"\[([^\]\n]+)\]\(([^)\s]+)\)", stash_link, t)
    t = re.sub(r"\*\*\*([^\n]+?)\*\*\*", stash_emph("bi"), t)
    t = re.sub(r"\*\*([^\n]+?)\*\*", stash_emph("b"), t)
    t = re.sub(r"__([^_\n]+?)__", stash_emph("b"), t)
    t = re.sub(r"\*([^*\n]+?)\*", stash_emph("i"), t)
    t = re.sub(r"(?<!\w)_([^_\n]+?)_(?!\w)", stash_emph("i"), t)
    t = escape_tex(t)

    def restore_emph(m):
        kind, inner = emphs[int(m.group(1))]
        inner = escape_tex(inner)
        if kind == "bi":
            return "\\textbf{\\textit{" + inner + "}}"
        if kind == "b":
            return "\\textbf{" + inner + "}"
        return "\\textit{" + inner + "}"

    t = re.sub(_P2 + r"(\d+)" + _P2, restore_emph, t)
    t = re.sub(_P0 + r"(\d+)" + _P0,
               lambda m: "\\texttt{" + escape_tex(codes[int(m.group(1))]) + "}", t)

    def restore_link(m):
        label, url = links[int(m.group(1))]
        return escape_tex(label) + " (" + escape_tex(url) + ")"
    return re.sub(_P1 + r"(\d+)" + _P1, restore_link, t)


_LIST_RE = re.compile(r"^(\s*)([-*\u2022]|\d+[.)])\s+(.*)$")


def _render_list(items: list[tuple[int, bool, str]]) -> str:
    """Recursive: items at min indent form this level; deeper attach to parent."""
    if not items:
        return ""
    base = min(i[0] for i in items)
    env = "enumerate" if items[0][1] else "itemize"
    out = [f"\\begin{{{env}}}"]
    i = 0
    while i < len(items):
        indent, _ordered, text = items[i]
        if indent > base:  # safety: shouldn't happen at top call
            i += 1
            continue
        j = i + 1
        nested = []
        while j < len(items) and items[j][0] > base:
            nested.append(items[j])
            j += 1
        line = f"\\item {_inline(text.strip())}"
        if nested:
            line += "\n" + _render_list(nested)
        out.append(line)
        i = j
    out.append(f"\\end{{{env}}}")
    return "\n".join(out)


def md_to_latex(text: str) -> str:
    lines = text.replace("\t", "    ").split("\n")
    blocks: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        fence = re.match(r"^\s*```", line)
        if fence:
            i += 1
            code = []
            while i < n and not re.match(r"^\s*```", lines[i]):
                if lines[i].strip():
                    code.append("{\\small\\texttt{" + escape_tex(lines[i].strip()) + "}}")
                i += 1
            i += 1  # closing fence
            if code:
                blocks.append(" \\\\\n".join(code))
            continue
        if re.match(r"^\s*(-{3,}|\*{3,})\s*$", line):
            blocks.append("\\medskip")
            i += 1
            continue
        hm = re.match(r"^\s*#{1,6}\s+(.*)$", line)
        if hm:
            blocks.append("\\textbf{" + _inline(hm.group(1).strip()) + "}")
            i += 1
            continue
        if _LIST_RE.match(line) and line[line.index(line.strip()[0]):].strip():
            items: list[tuple[int, bool, str]] = []
            while i < n:
                m = _LIST_RE.match(lines[i])
                if not m or not m.group(3).strip():
                    break
                items.append((len(m.group(1)), bool(re.match(r"\d", m.group(2))), m.group(3)))
                i += 1
            blocks.append(_render_list(items))
            continue
        # paragraph: join until blank / block starter
        para = [line]
        i += 1
        while i < n and lines[i].strip() and not _LIST_RE.match(lines[i]) \
                and not re.match(r"^\s*(```|#{1,6}\s+|[-*]{3,})\s*", lines[i]):
            para.append(lines[i])
            i += 1
        out_lines = []
        for k, pl in enumerate(para):
            hard = pl.endswith("  ")
            seg = _inline(pl.rstrip())
            if k < len(para) - 1:
                seg += " \\\\" if hard else " "
            out_lines.append(seg)
        blocks.append("".join(out_lines))
    return "\n\n".join(b for b in blocks if b.strip())


def plain_to_latex(text: str) -> str:
    paras = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    out = []
    for p in paras:
        out.append(" \\\\\n".join(escape_tex(line.strip()) for line in p.split("\n") if line.strip()))
    return "\n\n".join(out)


def convert(body: str, format: str) -> str:
    if format == "markdown":
        return md_to_latex(body)
    if format == "plain":
        return plain_to_latex(body)
    return body  # "latex" passthrough


def detect_format(body: str) -> str:
    """Guess a section's format: any backslash markup means latex (so plain
    conversion can never corrupt existing commands), then markdown, else plain."""
    if re.search(r"\\[^\s]", body):
        return "latex"
    if (re.search(r"(?m)^\s*(#{1,6}\s+|```|[-*\u2022]\s+|\d+[.)]\s+|>\s+)", body)
            or "**" in body or "__" in body or re.search(r"\*[^*\n]+\*", body)
            or re.search(r"\[[^\]]+\]\([^)]+\)", body) or "`" in body):
        return "markdown"
    return "plain"
