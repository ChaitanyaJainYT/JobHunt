"""Tailor base .tex with JD keywords. Prompt v2. LaTeX-safe."""
from __future__ import annotations

from pathlib import Path

from src import llm
from src.utils import sanitize_filename

TAILOR_PROMPT_V2 = """You are a resume tailor. Rewrite the LaTeX resume for the job below.
Rules:
- Inject missing keywords ONLY where truthful and contextual (skills, summary, experience bullets).
- Rewrite the professional summary/objective to align with job title: {title} at {company}.
- PRESERVE all LaTeX commands, environments, and structure. Do not add packages.
- Escape special chars in NEW text only: % -> \\%, & -> \\&, $ -> \\$, _ -> \\_, # -> \\#.
- Output the FULL .tex file only. No markdown fences, no explanation.

JOB TITLE: {title}
COMPANY: {company}
CORE REQUIREMENTS: {reqs}
MISSING SKILLS: {missing}

BASE TEX:
{tex}
"""


def tailor_resume(base_tex: str, title: str, company: str,
                  missing: list[str], reqs: list[str],
                  api_key: str = "", model: str = "gemini-3.6-flash",
                  groq_key: str = "",
                  groq_model: str = "openai/gpt-oss-120b") -> str:
    if "\\documentclass" not in base_tex:
        raise ValueError("Base .tex looks invalid (missing \\documentclass). Check main.tex.")
    prompt = TAILOR_PROMPT_V2.format(
        title=title, company=company,
        reqs=", ".join(reqs[:8]) or "-",
        missing=", ".join(missing[:10]) or "-",
        tex=base_tex[:15000],
    )
    out = llm.complete_text(prompt, api_key=api_key, model=model,
                              groq_key=groq_key, groq_model=groq_model)
    if "\\documentclass" not in out:
        raise ValueError("LLM did not return a valid .tex document. Retry or use --demo.")
    return out


def resume_stem(company: str, applicant: str = "Chaitanya Jain",
                date_str: str | None = None) -> str:
    """Filename stem: <COMPANY>_<Applicant_Name>_Resume_<DDMMYY>.

    Tectonic names the PDF after the .tex stem, so saving
    `<stem>.tex` yields `<stem>.pdf` automatically.
    """
    from datetime import date
    d = date_str or date.today().strftime("%d%m%y")
    who = sanitize_filename(applicant or "Candidate")
    return f"{sanitize_filename(company)}_{who}_Resume_{d}"


def save_tailored(tex: str, folder: Path, company: str,
                  applicant: str = "Chaitanya Jain",
                  date_str: str | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"{resume_stem(company, applicant, date_str)}.tex"
    p.write_text(tex, encoding="utf-8")
    return p
