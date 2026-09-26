"""Truthfulness guard: no skill may be claimed that isn't evidenced.

A tailored resume is checked against the candidate's evidence (main.tex +
LinkedIn profile). Any JD-vocabulary skill appearing in the tailored output
but in neither evidence source is reported for repair. Word-boundary matching
plus a small alias table keep false positives out.
"""
from __future__ import annotations

import re

# Canonical -> equivalent surface forms (checked both directions).
ALIASES: dict[str, list[str]] = {
    "aws": ["amazon web services"],
    "amazon web services": ["aws"],
    "gcp": ["google cloud platform", "google cloud"],
    "google cloud platform": ["gcp"],
    "google cloud": ["gcp"],
    "k8s": ["kubernetes"],
    "kubernetes": ["k8s"],
    "postgres": ["postgresql"],
    "postgresql": ["postgres"],
    "power bi": ["powerbi"],
    "powerbi": ["power bi"],
    "rest api": ["rest apis", "restful api", "restful apis", "rest"],
    "rest apis": ["rest api", "restful api", "restful apis", "rest"],
    "ai": ["artificial intelligence", "genai", "generative ai"],
    "artificial intelligence": ["ai"],
    "genai": ["ai", "generative ai"],
    "generative ai": ["ai", "genai"],
    "ml": ["machine learning"],
    "machine learning": ["ml"],
    "js": ["javascript"],
    "javascript": ["js"],
    "ts": ["typescript"],
    "typescript": ["ts"],
    "ci cd": ["cicd", "ci/cd"],
    "cicd": ["ci cd", "ci/cd"],
}

# Too generic to ever verdict on (single letters etc.).
_TOO_SHORT = re.compile(r"^[a-z0-9]$")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _variants(phrase: str) -> list[str]:
    p = norm(phrase)
    out = [p] if p else []
    for a in ALIASES.get(p, []):
        if a not in out:
            out.append(a)
    # reverse lookup: phrase may be the alias value, not the key
    for key, vals in ALIASES.items():
        if p in vals and key not in out:
            out.append(key)
    return out


def _mentions(text_norm: str, phrase: str) -> bool:
    """Word-boundary match so 'AI' doesn't hit 'said'/'daily'."""
    p = norm(phrase)
    if not p or _TOO_SHORT.match(p):
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(p) + r"(?![a-z0-9])", text_norm) is not None


def evidenced(phrase: str, evidence_text: str) -> bool:
    ev = norm(evidence_text)  # idempotent: safe on raw or pre-normalized text
    return any(_mentions(ev, v) for v in _variants(phrase))


def find_unverified_claims(tailored_tex: str, evidence_texts: list[str],
                           vocab: list[str]) -> list[str]:
    """Skills in vocab that the tailored resume claims without evidence.

    Returns de-duplicated offending phrases (original casing from vocab).
    """
    ev = norm(" ".join(evidence_texts))
    tex = norm(tailored_tex)
    out: list[str] = []
    seen: set[str] = set()  # exact-norm dedupe only ("Power BI" vs "JavaScript" must not collapse)
    for skill in vocab or []:
        s = (skill or "").strip()
        p = norm(s)
        if not s or p in seen:
            continue
        seen.add(p)
        if _mentions(tex, s) and not evidenced(s, ev):
            out.append(s)
    return out
