"""LLM wrapper: Gemini primary, Groq optional fallback. JSON-safe.

complete_json(prompt) -> dict. Strips ```json fences, retries once.
Raises LLMError with friendly fix (bad key / quota / --demo).
"""
from __future__ import annotations

import json
import re
import time


class LLMError(Exception):
    pass


def _is_transient(msg: str) -> bool:
    """Transient transport errors worth one automatic retry (e.g. Gemini 504)."""
    m = msg.lower()
    return any(s in m for s in (
        "503", "504", "deadline", "unavailable", "temporarily",
        "timed out", "timeout", "connection reset", "overloaded", "try again",
    ))


def _friendly_transport_error(msg: str) -> LLMError:
    if "API_KEY_INVALID" in msg or "401" in msg or "400" in msg and "key" in msg.lower():
        return LLMError(f"Gemini API key rejected. Fix: python agent.py setup. Detail: {msg[:200]}")
    if "429" in msg or "quota" in msg.lower():
        return LLMError(f"LLM quota exceeded ({msg[:150]}). Wait/upgrade or use --demo.")
    return LLMError(f"LLM call failed: {msg[:300]}")


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


def complete_json(prompt: str, api_key: str = "", model: str = "gemini-3.6-flash",
                  groq_key: str = "", groq_model: str = "openai/gpt-oss-120b",
                  timeout: int = 120) -> dict:
    """Call LLM, always return parsed JSON dict (retry once on parse fail)."""
    if not api_key and not groq_key:
        raise LLMError("No LLM key. Run 'python agent.py setup' or use --demo.")
    last: Exception | None = None
    for attempt in range(2):
        try:
            raw = _call_preferred(prompt, api_key, groq_key, model, groq_model, timeout)
            return _extract_json(raw)
        except (json.JSONDecodeError, ValueError) as e:
            last = e
            prompt = prompt + "\n\nIMPORTANT: return VALID JSON only, no markdown, no prose."
            continue
        except Exception as e:
            msg = str(e)
            if _is_transient(msg) and attempt == 0:
                last = e
                time.sleep(3)
                continue
            raise _friendly_transport_error(msg)
    raise LLMError(f"LLM returned invalid JSON twice ({last}). Try again or simplify resume/JD.")


def complete_text(prompt: str, api_key: str = "", model: str = "gemini-3.6-flash",
                  groq_key: str = "", groq_model: str = "openai/gpt-oss-120b",
                  timeout: int = 180) -> str:
    """Raw text completion (for .tex generation). Strips markdown fences."""
    if not api_key and not groq_key:
        raise LLMError("No LLM key. Run 'python agent.py setup' or use --demo.")
    last: Exception | None = None
    for attempt in range(2):
        try:
            raw = _call_preferred(prompt, api_key, groq_key, model, groq_model, timeout)
            return _strip_fences(raw)
        except Exception as e:
            msg = str(e)
            if _is_transient(msg) and attempt == 0:
                last = e
                time.sleep(3)
                continue
            raise _friendly_transport_error(msg)
    raise _friendly_transport_error(str(last))


def _call_gemini(prompt: str, api_key: str, model: str, timeout: int) -> str:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    m = genai.GenerativeModel(model)
    resp = m.generate_content(prompt, request_options={"timeout": timeout})
    return getattr(resp, "text", "") or ""


def _call_groq(prompt: str, groq_key: str, model: str = "openai/gpt-oss-120b") -> str:
    import requests
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {groq_key}"},
        json={"model": model or "openai/gpt-oss-120b",
              "messages": [{"role": "user", "content": prompt}],
              "temperature": 0.2},
        timeout=60,
    )
    if r.status_code in (401, 403):
        raise LLMError("Groq key rejected. Fix: python agent.py setup.")
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _call_preferred(prompt: str, api_key: str, groq_key: str,
                    model: str, groq_model: str, timeout: int) -> str:
    """Gemini first; on quota exhaustion auto-fall back to Groq if configured."""
    try:
        if api_key:
            return _call_gemini(prompt, api_key, model, timeout)
        return _call_groq(prompt, groq_key, groq_model)
    except Exception as e:
        msg = str(e)
        if api_key and groq_key and ("429" in msg or "quota" in msg.lower()):
            return _call_groq(prompt, groq_key, groq_model)
        raise


def fix_latex(broken_tex: str, error_log: str, api_key: str = "",
              model: str = "gemini-3.6-flash", groq_key: str = "",
              groq_model: str = "openai/gpt-oss-120b") -> str:
    """Ask LLM to repair LaTeX syntax only. Returns full .tex string."""
    import re
    prompt = (
        "Fix ONLY the LaTeX syntax errors. Do not change content, skills, or layout.\n"
        f"ERROR LOG:\n{error_log[:3000]}\n\nBROKEN TEX:\n{broken_tex[:12000]}\n\n"
        "Return the FULL corrected .tex file only, no markdown fences."
    )
    if not api_key and not groq_key:
        raise LLMError("No LLM key for LaTeX fix.")
    last: Exception | None = None
    for attempt in range(2):
        try:
            raw = _call_preferred(prompt, api_key, groq_key, model, groq_model, 120)
        except Exception as e:
            if _is_transient(str(e)) and attempt == 0:
                last = e
                time.sleep(3)
                continue
            raise _friendly_transport_error(str(e))
        # fix may come fenced; strip
        t = _strip_fences(raw)
        if "\\documentclass" not in t:
            raise LLMError("LaTeX fix did not return a .tex document.")
        return t
    raise _friendly_transport_error(str(last))
