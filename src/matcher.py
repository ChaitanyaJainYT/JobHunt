"""Skill matching: JD + raw main.tex -> MatchResult. Prompt v1 (versioned)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from src import llm
from src.utils import base_resume_path

MATCH_PROMPT_V1 = """You are a job-match analyzer. Compare JOB DESCRIPTION vs RESUME (LaTeX source).
Rules:
- Extract skills/requirements ONLY from the job description. Do not hallucinate.
- matching_skills: overlap between JD and resume. Lowercase, short phrases.
- missing_skills: in JD but not in resume.
- core_requirements: top 5-8 must-haves from JD.
- match_score: 0-100 integer, weighted by core requirement coverage.
Return VALID JSON only, exactly: {{"match_score": int, "matching_skills": [], "missing_skills": [], "core_requirements": []}}

JOB DESCRIPTION:
{jd}

RESUME (LaTeX):
{resume}
"""


@dataclass
class MatchResult:
    match_score: int
    matching_skills: list[str]
    missing_skills: list[str]
    core_requirements: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def read_base_resume(explicit: str | Path | None = None) -> tuple[str, Path]:
    """Return (tex_text, path_used). Falls back to sample with no crash."""
    p = Path(explicit) if explicit else base_resume_path()
    if not p.exists():
        raise FileNotFoundError(
            f"Base resume not found: {p}. Place your resume as main.tex in project root."
        )
    return p.read_text(encoding="utf-8"), p


def analyze_match(job_description: str, resume_tex: str,
                  api_key: str = "", model: str = "gemini-3.6-flash",
                  groq_key: str = "",
                  groq_model: str = "openai/gpt-oss-120b") -> MatchResult:
    if not job_description or not job_description.strip():
        raise ValueError("Empty job description. The posting may be expired or fetch failed.")
    if not resume_tex or not resume_tex.strip():
        raise ValueError("Empty resume text. Check main.tex.")
    prompt = MATCH_PROMPT_V1.format(jd=job_description[:12000], resume=resume_tex[:15000])
    data = llm.complete_json(prompt, api_key=api_key, model=model,
                               groq_key=groq_key, groq_model=groq_model)
    try:
        score = int(data.get("match_score", 0))
    except (TypeError, ValueError):
        score = 0
    score = max(0, min(100, score))
    def _list(k: str) -> list[str]:
        v = data.get(k, [])
        return [str(x).strip() for x in v if str(x).strip()][:30] if isinstance(v, list) else []
    return MatchResult(score, _list("matching_skills"), _list("missing_skills"),
                       _list("core_requirements"))


def save_match(m: MatchResult, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / "match.json"
    p.write_text(json.dumps(m.to_dict(), indent=2), encoding="utf-8")
    return p


def summary_line(m: MatchResult, apply_link: str = "") -> str:
    ok = ", ".join(m.matching_skills[:5]) or "-"
    miss = ", ".join(m.missing_skills[:5]) or "-"
    s = f"Match {m.match_score}% | OK: {ok} | Missing: {miss}"
    return s + (f" | Apply: {apply_link}" if apply_link else "")
