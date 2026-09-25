"""Candidate LinkedIn context for matching + tailoring.

Layers (first available wins, merged when several exist):
1. Local `profile.md` — paste LinkedIn About + Skills once. Always works.
2. Public profile page (`LINKEDIN_PROFILE_URL`) — headline/about/experience;
   LinkedIn hides Skills from logged-out pages, so this rarely yields skills.
3. (Future) RapidAPI profile endpoint via LINKEDIN_PROFILE_API_* envs.

Everything is best-effort: absence or failure never fails a run.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

PROFILE_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


@dataclass
class CandidateProfile:
    text: str = ""
    skills: list[str] = field(default_factory=list)
    source: str = "none"  # "none" | "file" | "url" | "file+url"


def _clean_skill(s: str) -> str:
    s = re.sub(r"^[\s*•\-–\d.)]+", "", s)  # bullets/numbers
    s = re.sub(r"[*_`#]+", "", s).strip()
    return re.sub(r"\s+", " ", s)


def parse_skills_block(text: str) -> list[str]:
    """Split comma/newline/bullet skill lists, dedupe (order kept), cap 60."""
    out: list[str] = []
    for chunk in re.split(r"[,;\n]+", text or ""):
        s = _clean_skill(chunk)
        if s and len(s) <= 60 and s.lower() not in {x.lower() for x in out}:
            out.append(s)
    return out[:60]


def load_local_profile(path: str | Path = "profile.md") -> tuple[str, list[str]]:
    """Read profile.md; also harvest any ## *Skill* section as skills."""
    p = Path(path)
    if not p.is_absolute():
        from src.utils import PROJECT_ROOT
        p = PROJECT_ROOT / path
    if not p.is_file():
        return "", []
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:
        return "", []
    skills: list[str] = []
    for m in re.finditer(r"(?ims)^##[^\n]*skill[^\n]*\n(.*?)(?=^##|\Z)", text):
        skills.extend(parse_skills_block(m.group(1)))
    # dedupe preserving order
    seen, uniq = set(), []
    for s in skills:
        if s.lower() not in seen:
            seen.add(s.lower())
            uniq.append(s)
    return text.strip(), uniq[:60]


def _clean_html(raw: str) -> str:
    import html as _html
    t = re.sub(r"<[^>]+>", " ", raw)
    return _html.unescape(re.sub(r"\s+", " ", t)).strip()


def fetch_public_profile(url: str, timeout: int = 20) -> dict:
    """Best-effort scrape of a public LinkedIn profile. Returns {} on any
    failure (999 bot-wall, login wall, network). Never raises."""
    import requests
    info: dict = {}
    try:
        resp = requests.get(url, headers={"User-Agent": PROFILE_UA}, timeout=timeout)
    except Exception:
        return {}
    if resp.status_code != 200:
        return {}
    page = resp.text
    if "authwall" in page[:5000].lower():
        return {}
    m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', page)
    if m:
        info["name"] = _clean_html(m.group(1))
    m = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', page)
    if m:
        info["about"] = _clean_html(m.group(1))[:2000]
    m = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.DOTALL)
    if m and not info.get("name"):
        info["name"] = _clean_html(m.group(1))
    for pat in (r'topcard__headline[^>]*>(.*?)</',
                r'top-card-layout__headline[^>]*>(.*?)</',
                r'"headline":"([^"]+)"'):
        m = re.search(pat, page, re.DOTALL)
        if m:
            info["headline"] = _clean_html(m.group(1))[:500]
            break
    skills: list[str] = []
    for pat in (r'"skillName":"([^"]+)"',
                r'skill[^>]{0,80}?>([^<]{2,60})</(?:span|a|p|div)>'):
        for m in re.finditer(pat, page):
            s = _clean_html(m.group(1))
            if s and len(s) <= 60 and s.lower() not in {x.lower() for x in skills}:
                skills.append(s)
        if skills:
            break
    if skills:
        info["skills"] = skills[:60]
    return info


def profile_text(info: dict) -> str:
    """Flatten fetched profile dict to prompt text."""
    if not info:
        return ""
    lines = []
    if info.get("name"):
        lines.append(f"Name: {info['name']}")
    if info.get("headline"):
        lines.append(f"Headline: {info['headline']}")
    if info.get("about"):
        lines.append(f"About: {info['about']}")
    if info.get("skills"):
        lines.append("LinkedIn Skills: " + ", ".join(info["skills"]))
    return "\n".join(lines)


def get_candidate_context(linkedin_url: str = "",
                          profile_file: str = "profile.md") -> CandidateProfile:
    """Total function: file + optional public URL merged. Never raises."""
    try:
        text, skills, sources = "", [], []
        if profile_file:
            t, s = load_local_profile(profile_file)
            if t.strip():
                text, skills, sources = t, s, ["file"]
        if linkedin_url and linkedin_url.strip().startswith("http"):
            info = fetch_public_profile(linkedin_url.strip())
            pt = profile_text(info)
            if pt:
                text = (text + "\n\n--- LinkedIn public profile ---\n" + pt).strip()
                for s in info.get("skills", []):
                    if s.lower() not in {x.lower() for x in skills}:
                        skills.append(s)
                sources.append("url")
        return CandidateProfile(text[:8000], skills[:60],
                                "+".join(sources) if sources else "none")
    except Exception:
        return CandidateProfile()
