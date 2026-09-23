"""Part 1: Job URL -> job_id -> RapidAPI -> Job dataclass.

Supports LinkedIn /jobs/view/<id>, currentJobId=, plus generic fallback.
Default RapidAPI endpoint: JSearch job-details (free tier), overridable via env.
All network errors are user-friendly, suggest --demo.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests


class JobURLError(Exception):
    pass


class JobFetchError(Exception):
    pass


@dataclass
class Job:
    title: str
    company: str
    description: str
    apply_link: str
    job_id: str
    source_url: str

    def to_dict(self) -> dict:
        return asdict(self)


def parse_job_id(url: str) -> str:
    """Extract job ID from LinkedIn / JSearch-style URLs."""
    if not url or not url.startswith(("http://", "https://")):
        raise JobURLError(
            f"Invalid job URL: {url!r}. Example: https://www.linkedin.com/jobs/view/4012345678"
        )
    try:
        parsed = urlparse(url)
    except Exception:
        raise JobURLError(f"Could not parse URL: {url!r}.")

    # 1. /jobs/view/<id>
    m = re.search(r"/jobs/view/(\d+)", parsed.path)
    if m:
        return m.group(1)
    # 2. ?currentJobId=<id>
    qs = parse_qs(parsed.query)
    if "currentJobId" in qs and qs["currentJobId"]:
        return qs["currentJobId"][0]
    # 3. generic numeric id in path (jsearch / other boards)
    m = re.search(r"(\d{6,})", url)
    if m:
        return m.group(1)
    # 4. Only allow slug fallback for job-board-like URLs; else raise.
    jobby = ("jobs" in parsed.path.lower() or "job" in parsed.path.lower()
             or "linkedin" in parsed.netloc or "indeed" in parsed.netloc
             or "jsearch" in parsed.netloc)
    if jobby:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", f"{parsed.netloc}{parsed.path}").strip("-")[:60]
        if slug:
            return slug
    raise JobURLError(
        f"Could not find job ID in URL: {url!r}. "
        "Example: https://www.linkedin.com/jobs/view/4012345678"
    )


def _pick(d: dict, *keys: str, default: str = "") -> str:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (list,)) and v:
            # e.g. apply_options: [ {link: ...} ]
            first = v[0]
            if isinstance(first, dict):
                for sub in ("link", "url", "apply_link"):
                    if first.get(sub):
                        return str(first[sub]).strip()
            elif isinstance(first, str) and first.strip():
                return first.strip()
    return default


def fetch_job(job_id_or_url: str, api_key: str, host: str, endpoint: str,
              timeout: int = 20) -> Job:
    """Call RapidAPI job-details endpoint, normalize to Job."""
    source_url = job_id_or_url if job_id_or_url.startswith("http") else ""
    job_id = parse_job_id(job_id_or_url) if source_url else job_id_or_url

    headers = {"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": host}
    # JSearch expects ?job_id=... ; other hosts may expect ?id=...
    params_variants = [{"job_id": job_id}, {"id": job_id}]
    last_err: Exception | None = None
    for params in params_variants:
        try:
            resp = requests.get(endpoint, headers=headers, params=params, timeout=timeout)
        except requests.Timeout as e:
            raise JobFetchError(
                f"RapidAPI timed out after {timeout}s. Check network or trial: "
                f"python agent.py --demo \"{source_url or job_id}\""
            ) from e
        except requests.RequestException as e:
            raise JobFetchError(
                f"Network error reaching RapidAPI ({e}). Trial offline: "
                f"python agent.py --demo \"{source_url or job_id}\""
            ) from e

        if resp.status_code in (401, 403):
            raise JobFetchError(
                "RapidAPI 401/403: invalid or missing RAPIDAPI_KEY, or not subscribed. "
                "Fix: RapidAPI dashboard -> subscribe JSearch free tier -> "
                "python agent.py setup. Or trial: --demo."
            )
        if resp.status_code == 429:
            raise JobFetchError(
                "RapidAPI 429 quota exceeded (free tier limit). Wait / upgrade, or use --demo."
            )
        if resp.status_code == 404 and params is not params_variants[-1]:
            last_err = JobFetchError(f"Endpoint 404 for params {params}, retrying...")
            continue
        if resp.status_code != 200:
            raise JobFetchError(
                f"RapidAPI error {resp.status_code}: {resp.text[:300]}. "
                "Check RAPIDAPI_HOST / RAPIDAPI_JOB_ENDPOINT in .env."
            )
        try:
            data = resp.json()
        except Exception as e:
            raise JobFetchError(f"RapidAPI returned non-JSON: {resp.text[:300]}") from e

        # Unwrap common envelopes: {data: {...}}, {data: [{...}]}, {...}
        payload = data.get("data", data)
        if isinstance(payload, list):
            payload = payload[0] if payload else {}
        if not isinstance(payload, dict):
            payload = {}

        title = _pick(payload, "job_title", "title", default="Unknown Title")
        company = _pick(payload, "employer_name", "company_name", "company", default="Unknown Company")
        desc = _pick(payload, "job_description", "description", default="")
        apply = _pick(payload, "job_apply_link", "apply_link", "apply_url", "link",
                      default=source_url)
        if not desc:
            raise JobFetchError(
                "RapidAPI returned empty job description. Response keys: "
                f"{sorted(payload.keys())[:12]}. The posting may be expired."
            )
        return Job(title=title, company=company, description=desc,
                   apply_link=apply or source_url, job_id=job_id,
                   source_url=source_url or apply)
    raise last_err or JobFetchError("Job fetch failed.")


def save_job(job: Job, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / "job.json"
    p.write_text(json.dumps(job.to_dict(), indent=2), encoding="utf-8")
    return p
