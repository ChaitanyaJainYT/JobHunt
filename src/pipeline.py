"""Full E2E orchestration. Exit codes: 0 ok, 2 config, 3 job fetch, 4 compile-failed.

run_apply(url, demo, out, cfg, sheet_client, _overrides) is injection-friendly for tests.
Demo mode: zero keys, fixtures only, fake PDF.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from src.config import ConfigError, load_config

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def _demo_job(url: str) -> dict:
    try:
        return json.loads((FIXTURES / "sample_job.json").read_text(encoding="utf-8"))
    except Exception:
        return {"title": "Demo Role", "company": "DemoCo", "description": "demo",
                "apply_link": url, "job_id": "demo123", "source_url": url}


def _find_existing_job_dir(job_id: str) -> Path | None:
    """Find output/*_<job_id>/ from a previous run (for --resume)."""
    from src.utils import OUTPUT_ROOT
    if not OUTPUT_ROOT.exists():
        return None
    cands = [d for d in OUTPUT_ROOT.iterdir()
             if d.is_dir() and d.name.endswith(f"_{job_id}")]
    return sorted(cands)[0] if cands else None


def run_apply(url: str, demo: bool = False, out: str | None = None,
              cfg=None, sheet_client=None, _overrides: dict | None = None,
              resume: bool = False) -> int:
    t0 = time.time()
    _ov = _overrides or {}
    try:
        cfg = cfg or load_config(auto_wizard=False, demo=demo)
    except ConfigError as e:
        print(f"\n[ERROR] {e}")
        return 2

    from src.utils import ensure_output_dir, get_logger
    from src.job_api import Job, JobFetchError, fetch_job_auto, parse_job_id, save_job
    from src.matcher import MatchResult, analyze_match, read_base_resume, save_match, summary_line
    from src.tailor import save_tailored, tailor_resume
    from src.compiler import LatexCompileError, compile_with_heal
    from src import sheets

    # --- 0. Resume shortcut: reuse saved job.json + match.json ---
    resumed_job = resumed_match = None
    if resume and not demo and out is None:
        try:
            rid = parse_job_id(url)
            rdir = _find_existing_job_dir(rid)
            if rdir and (rdir / "job.json").exists() and (rdir / "match.json").exists():
                resumed_job = json.loads((rdir / "job.json").read_text(encoding="utf-8"))
                resumed_match = json.loads((rdir / "match.json").read_text(encoding="utf-8"))
                print(f"[INFO] --resume: reusing {rdir.name}/job.json + match.json (no fetch/match calls).")
            else:
                print("[INFO] --resume: no saved job.json+match.json found, running full flow.")
        except Exception as e:
            print(f"[INFO] --resume unavailable ({e}), running full flow.")

    # --- 1. Job ---
    if demo:
        jd = _demo_job(url)
        from src.job_api import Job as _J
        job = _J(jd["title"], jd["company"], jd["description"],
                 jd.get("apply_link", url), jd.get("job_id", "demo123"), url)
        job_id = job.job_id
    elif resumed_job is not None:
        job = Job(resumed_job["title"], resumed_job["company"], resumed_job["description"],
                  resumed_job.get("apply_link", url), resumed_job.get("job_id", ""),
                  resumed_job.get("source_url", url))
        job_id = job.job_id
    else:
        try:
            fetch = _ov.get("fetch_job", fetch_job_auto)
            job = fetch(url, cfg.rapidapi_key, cfg.rapidapi_host, cfg.rapidapi_job_endpoint,
                        search_endpoint=cfg.rapidapi_search_endpoint,
                        country=cfg.rapidapi_country)
            job_id = job.job_id
        except Exception as e:
            print(f"\n[ERROR] Job fetch failed: {e}")
            return 3

    if out:
        folder = Path(out)
    else:
        # Same listing via another ID (LinkedIn URL vs JSearch token) must
        # update one folder, not spawn a duplicate.
        from src.job_api import find_existing_listing
        folder = find_existing_listing(job.company, job.title, job.apply_link,
                                       job.source_url)
        if folder is not None:
            print(f"[INFO] Same listing as {folder.name}; updating in place.")
        else:
            folder = ensure_output_dir(job.company, job_id)
    folder.mkdir(parents=True, exist_ok=True)
    log = get_logger("apply", folder / "run.log")

    # base resume hash (never modify check)
    try:
        base_tex, base_path = read_base_resume()
        base_hash = hashlib.sha256(base_tex.encode("utf-8")).hexdigest()[:12]
    except Exception as e:
        print(f"\n[ERROR] {e}")
        return 2
    log.info(f"base={base_path} company={job.company} job={job_id}")

    if demo:
        save_job(job, folder)
    else:
        try:
            save_job(job, folder)
        except Exception:
            pass

    # --- 1b. Candidate LinkedIn profile (optional supplement, never fatal) ---
    from src.profile import get_candidate_context
    prof = get_candidate_context(getattr(cfg, "linkedin_profile_url", ""),
                                 getattr(cfg, "linkedin_profile_file", "profile.md"))
    try:
        (folder / "profile.json").write_text(json.dumps(
            {"source": prof.source, "skills": prof.skills}, indent=2), encoding="utf-8")
    except Exception:
        pass
    if prof.skills:
        print(f"[INFO] LinkedIn profile ({prof.source}): {len(prof.skills)} skills merged.")
        log.info(f"profile source={prof.source} skills={len(prof.skills)}")

    # --- 2. Match ---
    try:
        if demo:
            mdata = json.loads((FIXTURES / "sample_match.json").read_text(encoding="utf-8"))
            match = MatchResult(mdata["match_score"], mdata["matching_skills"],
                                mdata["missing_skills"], mdata.get("core_requirements", []))
        elif resumed_match is not None:
            match = MatchResult(resumed_match["match_score"], resumed_match["matching_skills"],
                                resumed_match["missing_skills"],
                                resumed_match.get("core_requirements", []),
                                resumed_match.get("profile_skills", []))
        else:
            fn = _ov.get("analyze_match", analyze_match)
            match = fn(job.description, base_tex, api_key=cfg.gemini_api_key,
                       model=cfg.llm_model, groq_key=cfg.groq_api_key,
                       groq_model=cfg.groq_model, profile_text=prof.text)
        save_match(match, folder)
    except Exception as e:
        print(f"\n[ERROR] Skill match failed: {e}")
        return 3
    print(summary_line(match, job.apply_link))
    log.info(summary_line(match))

    # --- 3. Tailor ---
    try:
        if demo:
            tex = base_tex.replace("Python developer with 3 years",
                                   f"Python developer targeting {job.title} at {job.company}")
            if "\\documentclass" not in tex:
                tex = base_tex
        else:
            fn = _ov.get("tailor_resume", tailor_resume)
            tex = fn(base_tex, job.title, job.company, match.missing_skills,
                     match.core_requirements, api_key=cfg.gemini_api_key,
                     model=cfg.llm_model, groq_key=cfg.groq_api_key,
                     groq_model=cfg.groq_model, profile_text=prof.text)
        tex_path = save_tailored(tex, folder, job.company,
                                   applicant=cfg.applicant_name)
    except Exception as e:
        print(f"\n[ERROR] Resume tailor failed: {e}")
        return 3

    # --- 4. Compile (continue on failure) ---
    pdf_display = "FAILED"
    pdf_ok = False
    try:
        if demo:
            pdf = tex_path.with_suffix(".pdf")
            pdf.write_bytes(b"%PDF-1.4 demo fake\n")
            pdf_display = str(pdf)
            pdf_ok = True
        else:
            fn = _ov.get("compile_with_heal", compile_with_heal)
            pdf = fn(tex_path, api_key=cfg.gemini_api_key, model=cfg.llm_model,
                     groq_key=cfg.groq_api_key, groq_model=cfg.groq_model)
            pdf_display = str(pdf)
            pdf_ok = True
    except LatexCompileError as e:
        from src.compiler import LatexCompileError as _L
        log.error(f"compile failed: {e}")
        print(f"\n[WARN] PDF compile failed (tex preserved): {e}")
        print(f"  Manual retry: tectonic --outdir \"{tex_path.parent}\" \"{tex_path}\"")
        pdf_display = f"FAILED (see {tex_path.stem}.tectonic.log)"
    except Exception as e:
        log.error(f"compile failed: {e}")
        pdf_display = f"FAILED ({e})"

    # --- 5. Sheets log ---
    row_no = "?"
    try:
        if demo and sheet_client is None:
            print(f"[DEMO] Sheet log skipped (no creds). Would log: {job.company} | {job.title} | {match.match_score}%")
            row_no = "demo"
        else:
            client = sheet_client if (demo or sheet_client is not None) else None
            row_no = sheets.log_application(job, match, pdf_display, job.apply_link,
                                            cfg.google_sheet_id, cfg.google_credentials_file,
                                            client=client)
    except Exception as e:
        print(f"[WARN] Sheets log failed (PDF still ready): {e}")
        row_no = "failed"

    dt = int(time.time() - t0)
    print(f"\n[OK] Done in {dt}s  (base {base_hash})")
    print(f"Match: {match.match_score}% | PDF: {pdf_display}")
    print(f"Apply here (manual): {job.apply_link}")
    print(f"Logged to Sheet row {row_no} (Ready to Apply)")
    print("Next: apply manually in browser, then: python agent.py check-mail")
    if not pdf_ok:
        return 4
    return 0


def run_check_mail_flow(days: int = 14, demo: bool = False, cfg=None,
                        sheet_client=None, email_fetcher=None,
                        seen_path: Path | None = None) -> int:
    try:
        cfg = cfg or load_config(auto_wizard=False, demo=demo)
    except ConfigError as e:
        print(f"\n[ERROR] {e}")
        return 2
    from src import sheets
    from src import gmail as G

    if demo and email_fetcher is None:
        try:
            items = json.loads((FIXTURES / "sample_emails.json").read_text(encoding="utf-8"))
        except Exception:
            items = []
        def email_fetcher(company, _items=items):
            return [G.Email(i["id"], i["company"], i["subject"], i["date"], i["body"])
                    for i in _items if i["company"] == company]
        companies = sorted({i["company"] for i in items}) or ["Acme Corp"]
        if sheet_client is None:
            from src.sheets import FakeClient
            sheet_client = FakeClient()
        # seed fake sheet so demo shows updates
        try:
            ws = sheet_client.open_by_key("demo").sheet1
            if not ws.get_all_values():
                ws.append_row(sheets.HEADER)
                for c in companies:
                    ws.append_row(["2026-09-01", c, "Demo Role", "75", "p", "u", "Applied", ""])
        except Exception:
            pass
        # Deterministic keyword classifier: no network in demo.
        def _demo_classify(subject: str, body: str, *a, **k):
            t = f"{subject} {body}".lower()
            if "not moving forward" in t or "will not be moving" in t:
                return "Rejection", 0.95
            if "invite" in t and "interview" in t:
                return "Interview Invite", 0.95
            if "assessment" in t or "hackerrank" in t or "test" in t and "interview" not in t:
                return "Assessment/Test", 0.8
            if "offer" in t and ("compensation" in t or "pleased to offer" in t):
                return "Offer", 0.9
            if "courses" in t or "50%" in t or "50 percent" in t:
                return "Marketing/Spam", 0.99
            return "Other", 0.5
        orig = G.classify_email
        G.classify_email = _demo_classify  # type: ignore
        try:
            G.run_check_mail(companies, "demo", days=days, api_key="demo",
                             seen_path=seen_path or G.SEEN_DEFAULT,
                             email_fetcher=email_fetcher, sheet_client=sheet_client)
        finally:
            G.classify_email = orig
        print("\n[OK] DEMO check-mail done (fixtures). Real run: python agent.py check-mail")
        return 0

    # real path
    try:
        companies = sheets.get_tracked_companies(cfg.google_sheet_id, cfg.google_credentials_file)
    except Exception as e:
        print(f"\n[ERROR] Could not read Sheet: {e}")
        return 3
    G.run_check_mail(companies, cfg.google_sheet_id, cfg.google_credentials_file,
                     days=days, api_key=cfg.gemini_api_key, model=cfg.llm_model,
                     groq_key=cfg.groq_api_key, groq_model=cfg.groq_model,
                     seen_path=seen_path or G.SEEN_DEFAULT,
                     email_fetcher=email_fetcher, sheet_client=sheet_client)
    return 0
