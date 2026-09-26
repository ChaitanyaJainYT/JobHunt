"""LLM wrapper: Gemini (google-genai SDK) primary, Groq optional fallback.

complete_json(prompt) -> dict. Strips ```json fences, retries once.
Raises LLMError with friendly fix (bad key / quota / --demo).
"""
from __future__ import annotations

import json
import re
import time

from src.keypool import get_pool, is_quota_error


class LLMError(Exception):
    pass


class _Drained(Exception):
    """All keys of one provider cooling down. Carries context for the final error."""

    def __init__(self, provider: str, tried: int, last: Exception | None):
        self.provider = provider
        self.tried = tried
        self.last = last
        super().__init__(
            f"quota exhausted, tried {tried} {provider} key(s): {last}")


def _quiet_sdk_logging() -> None:
    try:
        import logging
        logging.getLogger("google_genai.models").setLevel(logging.ERROR)
    except Exception:
        pass


_quiet_sdk_logging()


def _is_transient(msg: str) -> bool:
    """Transient transport errors worth one automatic retry (e.g. Gemini 504)."""
    m = msg.lower()
    return any(s in m for s in (
        "503", "504", "deadline", "unavailable", "temporarily",
        "timed out", "timeout", "connection reset", "overloaded", "try again",
    ))


def _friendly_transport_error(err: Exception | None) -> LLMError:
    """Map SDK/HTTP failures (google-genai APIError has .code) to user fixes."""
    code = getattr(err, "code", None)
    msg = str(err) if err is not None else ""
    low = msg.lower()
    if (code in (400, 401, 403) and ("key" in low or "API_KEY_INVALID" in msg)
            or "API_KEY_INVALID" in msg or "API key not valid" in msg
            or "401" in msg or "400" in msg and "key" in low):
        return LLMError(f"Gemini API key rejected. Fix: python agent.py setup. Detail: {msg[:200]}")
    if code == 429 or "429" in msg or "quota" in low:
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
            raise _friendly_transport_error(e)
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
            raise _friendly_transport_error(e)
    raise _friendly_transport_error(last)


def _call_gemini(prompt: str, api_key: str | list[str], model: str, timeout: int) -> str:
    from google import genai
    from google.genai import types
    pool = get_pool("gemini", api_key)
    if not pool:
        raise LLMError("No Gemini key. Run 'python agent.py setup' or use --demo.")
    last: Exception | None = None
    tried = 0
    for _ in range(len(pool)):
        key = pool.next()
        tried += 1
        try:
            client = genai.Client(api_key=key)
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    http_options=types.HttpOptions(timeout=max(1, timeout) * 1000)),
            )
            pool.report_success(key)
            return getattr(resp, "text", "") or ""
        except Exception as e:
            if is_quota_error(e):
                pool.report_quota(key)
                last = e
                continue
            raise
    if tried > 1 and last is not None:
        raise _Drained("Gemini", tried, last)
    raise last if last is not None else LLMError("Gemini call failed.")


def _call_groq(prompt: str, groq_key: str | list[str], model: str = "openai/gpt-oss-120b") -> str:
    import requests
    pool = get_pool("groq", groq_key)
    if not pool:
        raise LLMError("No Groq key. Run 'python agent.py setup' or use --demo.")
    last: Exception | None = None
    tried = 0
    for _ in range(len(pool)):
        key = pool.next()
        tried += 1
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": model or "openai/gpt-oss-120b",
                      "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.2},
                timeout=60,
            )
            if r.status_code in (401, 403):
                raise LLMError("Groq key rejected. Fix: python agent.py setup.")
            r.raise_for_status()
            pool.report_success(key)
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            if isinstance(e, LLMError) or not is_quota_error(e):
                raise
            pool.report_quota(key)
            last = e
    if tried > 1 and last is not None:
        raise _Drained("Groq", tried, last)
    raise last if last is not None else LLMError("Groq call failed.")


def _call_preferred(prompt: str, api_key: str | list[str], groq_key: str | list[str],
                    model: str, groq_model: str, timeout: int) -> str:
    """Gemini pool first; on exhaustion fall back to the Groq pool if configured."""
    from src.keypool import count_keys
    if count_keys(api_key):
        try:
            return _call_gemini(prompt, api_key, model, timeout)
        except _Drained:
            pass  # drained pool below; try Groq if configured
        except Exception as e:
            if not (count_keys(groq_key) and is_quota_error(e)):
                raise
            # single-key original quota error below; try Groq if configured
    if count_keys(groq_key):
        return _call_groq(prompt, groq_key, groq_model)
    raise LLMError("No LLM key. Run 'python agent.py setup' or use --demo.")


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
            raise _friendly_transport_error(e)
        # fix may come fenced; strip
        t = _strip_fences(raw)
        if "\\documentclass" not in t:
            raise LLMError("LaTeX fix did not return a .tex document.")
        return t
    raise _friendly_transport_error(last)
