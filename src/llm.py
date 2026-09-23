"""LLM wrapper: Gemini primary, Groq optional fallback. JSON-safe.

complete_json(prompt) -> dict. Strips ```json fences, retries once.
Raises LLMError with friendly fix (bad key / quota / --demo).
"""
from __future__ import annotations

import json
import re


class LLMError(Exception):
    pass


def _strip_fences(text: str) -> str:
    t = text.strip()
    # ```json ... ``` or ``` ... ```
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return t


def _extract_json(text: str) -> dict:
    t = _strip_fences(text)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        # trailing prose: find first {...} block
        m = re.search(r"\{.*\}", t, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def complete_json(prompt: str, api_key: str = "", model: str = "gemini-1.5-flash",
                  groq_key: str = "", timeout: int = 60) -> dict:
    """Call LLM, always return parsed JSON dict (retry once on parse fail)."""
    if not api_key and not groq_key:
        raise LLMError("No LLM key. Run 'python agent.py setup' or use --demo.")
    last: Exception | None = None
    for attempt in range(2):
        try:
            raw = _call_gemini(prompt, api_key, model, timeout) if api_key else _call_groq(prompt, groq_key, model)
            return _extract_json(raw)
        except (json.JSONDecodeError, ValueError) as e:
            last = e
            prompt = prompt + "\n\nIMPORTANT: return VALID JSON only, no markdown, no prose."
            continue
        except Exception as e:
            msg = str(e)
            if "API_KEY_INVALID" in msg or "401" in msg or "400" in msg and "key" in msg.lower():
                raise LLMError(f"Gemini API key rejected. Fix: python agent.py setup. Detail: {msg[:200]}")
            if "429" in msg or "quota" in msg.lower():
                raise LLMError(f"LLM quota exceeded ({msg[:150]}). Wait/upgrade or use --demo.")
            raise LLMError(f"LLM call failed: {msg[:300]}")
    raise LLMError(f"LLM returned invalid JSON twice ({last}). Try again or simplify resume/JD.")


def complete_text(prompt: str, api_key: str = "", model: str = "gemini-1.5-flash",
                  groq_key: str = "", timeout: int = 90) -> str:
    """Raw text completion (for .tex generation). Strips markdown fences."""
    if not api_key and not groq_key:
        raise LLMError("No LLM key. Run 'python agent.py setup' or use --demo.")
    try:
        raw = _call_gemini(prompt, api_key, model, timeout) if api_key else _call_groq(prompt, groq_key, model)
    except Exception as e:
        msg = str(e)
        if "429" in msg or "quota" in msg.lower():
            raise LLMError(f"LLM quota exceeded ({msg[:150]}). Wait/upgrade or use --demo.")
        raise LLMError(f"LLM call failed: {msg[:300]}")
    return _strip_fences(raw)


def _call_gemini(prompt: str, api_key: str, model: str, timeout: int) -> str:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    m = genai.GenerativeModel(model)
    resp = m.generate_content(prompt, request_options={"timeout": timeout})
    return getattr(resp, "text", "") or ""


def _call_groq(prompt: str, groq_key: str, model: str) -> str:
    import requests
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {groq_key}"},
        json={"model": "llama-3.1-8b-instant",
              "messages": [{"role": "user", "content": prompt}],
              "temperature": 0.2},
        timeout=60,
    )
    if r.status_code in (401, 403):
        raise LLMError("Groq key rejected. Fix: python agent.py setup.")
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def fix_latex(broken_tex: str, error_log: str, api_key: str = "",
              model: str = "gemini-1.5-flash", groq_key: str = "") -> str:
    """Ask LLM to repair LaTeX syntax only. Returns full .tex string."""
    import re
    prompt = (
        "Fix ONLY the LaTeX syntax errors. Do not change content, skills, or layout.\n"
        f"ERROR LOG:\n{error_log[:3000]}\n\nBROKEN TEX:\n{broken_tex[:12000]}\n\n"
        "Return the FULL corrected .tex file only, no markdown fences."
    )
    if not api_key and not groq_key:
        raise LLMError("No LLM key for LaTeX fix.")
    raw = _call_gemini(prompt, api_key, model, 60) if api_key else _call_groq(prompt, groq_key, model)
    # fix may come fenced; strip
    t = _strip_fences(raw)
    if "\\documentclass" not in t:
        raise LLMError("LaTeX fix did not return a .tex document.")
    return t
