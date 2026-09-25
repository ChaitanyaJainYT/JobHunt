"""LaTeX resume section model: parse a .tex document into editable sections
and rebuild it. Powers the UI-based (non-raw) resume editor.

Model:
- head: everything through \\begin{document} (packages, styling — preserved verbatim)
- sections: [Section(title=None (preamble: name/contact block), ...),
              Section(title, starred, body), ...]
- tail: original text from \\end{document} on (usually just the closer)

Rebuild keeps head/tail byte-identical and re-emits sections in order.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Section:
    title: str | None  # None == preamble (contact block before first \\section)
    starred: bool
    body: str
    format: str = "latex"  # "latex" | "markdown" | "plain" (editor-side only)

    def to_dict(self) -> dict:
        return {"title": self.title, "starred": self.starred,
                "body": self.body, "format": self.format}

    @staticmethod
    def from_dict(d: dict) -> "Section":
        title = d.get("title")
        fmt = str(d.get("format", "latex") or "latex")
        return Section(title=str(title) if title else None,
                       starred=bool(d.get("starred", True)),
                       body=str(d.get("body", "")),
                       format=fmt if fmt in ("latex", "markdown", "plain") else "latex")


@dataclass
class ParsedResume:
    head: str
    sections: list[Section]
    tail: str

    def to_dict(self) -> dict:
        return {"head": self.head, "tail": self.tail,
                "sections": [s.to_dict() for s in self.sections]}


_SECTION_RE = re.compile(r"\\section(\*?)\{([^}]*)\}")


def parse_resume(tex: str) -> ParsedResume:
    """Split a LaTeX resume into head + sections. Raises ValueError if invalid."""
    if "\\documentclass" not in tex:
        raise ValueError("Not a LaTeX document (missing \\documentclass).")
    begin = re.search(r"\\begin\{document\}", tex)
    end = re.search(r"\\end\{document\}", tex)
    if not begin or not end or end.start() < begin.end():
        raise ValueError("Not a compilable document (missing \\begin/\\end{document}).")
    head = tex[:begin.end()]
    body = tex[begin.end():end.start()]
    tail = tex[end.start():]
    from src.md2latex import detect_format
    matches = list(_SECTION_RE.finditer(body))
    sections: list[Section] = []
    if not matches:
        pre = body.strip("\n")
        sections.append(Section(None, False, pre, detect_format(pre)))
    else:
        pre = body[:matches[0].start()].strip("\n")
        sections.append(Section(None, False, pre, detect_format(pre)))
        for i, m in enumerate(matches):
            start = m.end()
            stop = matches[i + 1].start() if i + 1 < len(matches) else len(body)
            text = body[start:stop].strip("\n")
            sections.append(Section(m.group(2).strip(),
                                    starred=m.group(1) == "*",
                                    body=text, format=detect_format(text)))
    return ParsedResume(head, sections, tail)


def build_resume(head: str, sections: list[Section],
                 tail: str = "\n\\end{document}\n") -> str:
    """Rebuild full .tex from head + sections. Section order is preserved;
    entries with empty titles (except preamble) are skipped."""
    if "\\documentclass" not in head or "\\begin{document}" not in head:
        raise ValueError("Invalid document head.")
    from src.md2latex import convert
    parts = [head.rstrip() + "\n"]
    for s in sections:
        tex = convert(s.body.strip(), s.format)
        if s.title is None:
            if tex.strip():
                parts.append(tex.strip() + "\n")
        else:
            title = s.title.strip()
            if not title:
                continue
            cmd = "\\section*" if s.starred else "\\section"
            parts.append(f"{cmd}{{{title}}}\n{tex.strip()}\n")
    tail = tail if "\\end{document}" in tail else "\n\\end{document}\n"
    parts.append(tail if tail.startswith("\n") else "\n" + tail)
    return "\n".join(p.rstrip() for p in parts if p.strip()) + "\n"
