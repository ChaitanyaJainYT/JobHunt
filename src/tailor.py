"""Tailor base .tex with JD keywords. Prompt v2. LaTeX-safe."""
from __future__ import annotations

from pathlib import Path

from src import llm
from src.utils import sanitize_filename

TAILOR_PROMPT_V4 = """You are a resume tailor. Rewrite the LaTeX resume for the job below.
HONESTY RULES (highest priority — a false skill can cost the candidate the job):
- The Skills section, tools lists, and experience bullets may ONLY contain skills evidenced in BASE TEX or CANDIDATE LINKEDIN PROFILE.
- The following skills the candidate DOES NOT HAVE. Never list them as possessed skills, tools, or experience — not directly, not via synonyms or crowded tool lists, not in fabricated bullets:
  {missing}
- If a missing skill is genuinely adjacent to real experience, you may OMIT it silently. Never reframe it as a capability.
- Rewrite the professional summary/objective to align with job title: {title} at {company}, using only evidenced background.
- PRESERVE all LaTeX commands, environments, and structure. Do not add packages.
- Escape special chars in NEW text only: % -> \\%, & -> \\&, $ -> \\$, _ -> \\_, # -> \\#.
- Output the FULL .tex file only. No markdown fences, no explanation.

JOB TITLE: {title}
COMPANY: {company}
CORE REQUIREMENTS (for emphasis of REAL experience only): {reqs}

CANDIDATE LINKEDIN PROFILE:
{profile}

BASE TEX:
{tex}
"""

REPAIR_PROMPT = """You are a resume honesty editor. The resume below contains skills the candidate DOES NOT HAVE. Remove every such claim with minimal edits.
Rules:
- Delete the listed skills from Skills/tools lists. Rewrite or delete any bullet whose core claim depends on them (keep bullets that stand without them).
- Change NOTHING else: same structure, same LaTeX, same remaining content.
- Output the FULL .tex file only. No markdown fences, no explanation.

SKILLS TO REMOVE (candidate does not have these):
{bad}

CANDIDATE BACKGROUND (full truthful evidence — skills must come from here):
{evidence}

RESUME TO FIX:
{tex}
"""


def tailor_resume(base_tex: str, title: str, company: str,
                  missing: list[str], reqs: list[str],
                  api_key: str = "", model: str = "gemini-3.6-flash",
                  groq_key: str = "",
                  groq_model: str = "openai/gpt-oss-120b",
                  profile_text: str = "") -> str:
    if "\\documentclass" not in base_tex:
        raise ValueError("Base .tex looks invalid (missing \\documentclass). Check main.tex.")
    prompt = TAILOR_PROMPT_V4.format(
        title=title, company=company,
        reqs=", ".join(reqs[:8]) or "-",
        missing=", ".join(missing[:12]) or "(none — candidate covers everything)",
        profile=(profile_text or "(none)")[:3000],
        tex=base_tex[:15000],
    )
    out = llm.complete_text(prompt, api_key=api_key, model=model,
                              groq_key=groq_key, groq_model=groq_model)
    if "\\documentclass" not in out:
        raise ValueError("LLM did not return a valid .tex document. Retry or use --demo.")
    return out


def remove_unverified_claims(broken_tex: str, bad_skills: list[str],
                             evidence_text: str, api_key: str = "",
                             model: str = "gemini-3.6-flash", groq_key: str = "",
                             groq_model: str = "openai/gpt-oss-120b") -> str:
    """One repair pass: strip skills the candidate doesn't have. Returns full .tex."""
    prompt = REPAIR_PROMPT.format(
        bad=", ".join(bad_skills[:15]),
        evidence=evidence_text[:12000],
        tex=broken_tex[:15000],
    )
    out = llm.complete_text(prompt, api_key=api_key, model=model,
                             groq_key=groq_key, groq_model=groq_model)
    if "\\documentclass" not in out:
        raise ValueError("Repair did not return a valid .tex document.")
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
