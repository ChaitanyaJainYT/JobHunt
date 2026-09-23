# Final Implementation Plan - Local Automated Job Application Assistant

Source requirement: `ai_agent_implementation_plan.md`
Target env: Windows + Python 3.12.10 (verified), local-only, single entrypoint CLI.
Date: 2026-09-23

## 1. Goals & UX Principles

**Goal:** `python agent.py "<job-url>"` does everything, with minimum prompts.

UX rules for all parts:
1. **One entrypoint:** `agent.py` with subcommands `apply`, `check-mail`, `doctor`, `setup`.
   - `python agent.py "https://linkedin.com/jobs/view/123"` == `python agent.py apply --url "..."` (smart default).
   - `python agent.py --check-mail` == `python agent.py check-mail`.
2. **Zero-config start:** missing `.env` -> auto-copy from `.env.example` + interactive wizard (ask only missing keys, validate, save).
3. **One health command:** `python agent.py doctor` checks Python version, `tectonic` in PATH, `.env` keys, `main.tex` exists, Google `credentials.json`/`token.json`, network to RapidAPI/Gemini. Prints PASS/FAIL table + fix hints. No traceback on user errors.
4. **Offline/mock mode:** `--demo` / `--mock` runs full pipeline with fixtures, no API keys, no network. Required for tests and first-run trial.
5. **Idempotent outputs:** `output/<Company>_<JobId>/` holds `job.json`, `match.json`, `<Company>_Resume.tex`, `<Company>_Resume.pdf`, `run.log`. Re-runs overwrite safely, never touch `main.tex` (read-only base).
6. **Never apply automatically:** only prepare PDF + log `Application URL` for manual apply. No Selenium/Playwright.

---

## 2. Target Project Structure

```
JobHunt/
  agent.py                 # single CLI entrypoint (argparse, dispatches to src/)
  requirements.txt
  .env.example
  .env                     # gitignored, created by wizard
  main.tex                 # user-provided base resume (read-only) + sample fallback
  credentials.json         # user-provided Google OAuth Desktop client (gitignored)
  token.json               # auto-created after first OAuth (gitignored)
  src/
    __init__.py
    config.py              # load .env, validate, wizard
    cli.py                 # argparse definitions
    doctor.py              # dependency + config checks
    job_api.py             # URL -> job_id -> RapidAPI -> Job dataclass
    llm.py                 # Gemini (+Groq fallback) wrapper, JSON-safe
    matcher.py             # match_score / missing / matching / core_requirements
    tailor.py              # tailored .tex generation + LaTeX sanitize
    compiler.py            # tectonic subprocess + self-heal retry
    sheets.py              # gspread log + read companies
    gmail.py               # Gmail search + fetch + classify + update sheet
    pipeline.py            # orchestrate apply flow end-to-end
    utils.py               # paths, sanitize_filename, logging
  tests/
    conftest.py
    fixtures/
      sample_job.json
      sample_main.tex
      sample_match.json
      sample_emails.json
    test_config.py
    test_job_api.py
    test_matcher.py
    test_tailor.py
    test_compiler.py
    test_sheets.py
    test_gmail.py
    test_pipeline.py       # E2E with all mocks (--demo path)
  output/                  # gitignored, per-job artifacts
```

Keep each Part < ~350 lines diff so it fits in agent limits.

---

## 3. Implementation Parts (in order)

### PART 0 - Scaffold, Config, CLI, Doctor [FOUNDATION - do first]
**Why first:** unblocks everything, no external keys needed.

**Build:**
- `requirements.txt`: `python-dotenv, requests, google-generativeai, gspread, oauth2client, google-api-python-client, google-auth-httplib2, google-auth-oauthlib, pytest, pytest-mock`
- `src/config.py`: `load_config(auto_wizard=True)`, `REQUIRED_KEYS = [GEMINI_API_KEY, RAPIDAPI_KEY, ...]` with `RAPIDAPI_HOST` default, `GOOGLE_SHEET_ID`, `GOOGLE_CREDENTIALS_FILE`. Returns dataclass. Missing key in `--demo` mode -> warn not fail.
- `src/utils.py`: `ensure_output_dir(company, job_id)`, `sanitize_filename()`, file logger to `run.log` + console.
- `src/doctor.py`: `run_doctor() -> list[CheckResult]` for: python>=3.10, tectonic (`shutil.which`), main.tex exists, .env keys present (masked), credentials.json exists, RapidAPI reachable (optional quick ping, timeout 5s).
- `agent.py` + `src/cli.py`: commands `apply --url --demo --mock --out`, `check-mail --days --demo`, `doctor`, `setup` (runs wizard). Bare URL positional arg routes to `apply`. Friendly errors via `parser.error` override + try/except in `main()` printing `Fix: ...`.
- `.env.example`, `.gitignore` update (` .env, token.json, credentials.json, output/`), `main.tex.sample` minimal compilable resume if user has no `main.tex`.

**Testcases (Part 0):**
- `test_config.py`:
  1. `test_load_valid_env` - temp .env with all keys -> config loads.
  2. `test_missing_key_raises_friendly` - missing GEMINI_API_KEY without demo -> `ConfigError` message contains key name + fix.
  3. `test_demo_mode_skips_keys` - `--demo` with empty env -> loads with placeholders.
  4. `test_wizard_creates_env` - mocked `input()` creates `.env` file.
- `test_doctor.py` (or manual):
  5. `test_doctor_reports_tectonic_missing` - mock `shutil.which->None`, assert FAIL row mentions install URL.
  6. Manual: `python agent.py doctor`, `python agent.py --help`, `python agent.py --demo "dummy"` all exit 0.

**Done when:** `doctor`, `--help`, `--demo` path run with no keys installed.

**Human steps:** 0 (just run commands).

---

### PART 1 - Job Ingestion via RapidAPI
**Depends:** Part 0.

**Build (`src/job_api.py`):**
- `parse_job_id(url: str) -> str`: LinkedIn `/jobs/view/<id>`, `currentJobId=`, JSearch query fallback. Raise `JobURLError` with example on failure.
- `fetch_job(job_id_or_url) -> Job(title, company, description, apply_link, job_id, source_url)`: uses `RAPIDAPI_HOST` + `RAPIDAPI_KEY`, header `X-RapidAPI-Key/Host`, GET with timeout 20s, normalize variants (`job_title/title`, `company_name/company`, `job_description/description`, `apply_link/job_apply_link`). On 401/403/429 raise friendly error (check key/quota). On network error, suggest `--demo`.
- Cache raw response to `output/.../job.json`.
- Support at least JSearch (`jsearch.p.rapidapi.com/job-details`) as default free tier; make host+endpoint overridable via env `RAPIDAPI_JOB_ENDPOINT`.

**Testcases:**
- `test_job_api.py` (mock `requests.get`):
  1. `test_parse_linkedin_view_url` - `.../jobs/view/4012345678` -> `4012345678`.
  2. `test_parse_linkedin_search_url` - `currentJobId=...` variant.
  3. `test_invalid_url_raises` - `https://google.com` -> friendly error.
  4. `test_fetch_normalizes_fields` - fake JSON with alternate keys -> `Job` correct.
  5. `test_fetch_401_message` - mocked 401 -> message contains "RAPIDAPI_KEY" + quota hint.
  6. `test_fetch_timeout` - mocked timeout -> suggests `--demo`.
  7. Manual: `python agent.py apply --url <real-url> --demo` uses `fixtures/sample_job.json` no network.

**Done when:** real + mocked fetch both produce `Job` and `job.json`.

**Human steps:** 1 - paste RapidAPI key into `.env` (wizard prompts once).

---

### PART 2 - LLM Layer + Skill Matching
**Depends:** Part 0. Testable with fixtures, no Part 1 needed.

**Build (`src/llm.py`, `src/matcher.py`):**
- `src/llm.py`: `get_client()` prefers `GEMINI_API_KEY` (`google-generativeai`, model `gemini-1.5-flash` env-overridable `LLM_MODEL`), optional `GROQ_API_KEY` fallback. `complete_json(prompt, schema_hint)`: forces JSON, strips ```json fences, `json.loads`, retries once on parse fail with "return valid JSON only". In `--demo` returns fixture without calling network.
- `src/matcher.py`: `analyze_match(job_description, resume_tex) -> MatchResult(match_score 0-100, missing_skills[], matching_skills[], core_requirements[])`. Prompt v1 (fixed string, versioned): includes clamping 0-100, "extract from JD only, no hallucinated skills", returns JSON only. Reads `main.tex` as text (no LaTeX parsing, raw string per spec). Saves `match.json`.
- Print human summary: `Match 78% | ✅ python, sql | ❌ kubernetes | Apply: <link>`.

**Testcases:**
- `test_matcher.py` (mock `llm.complete_json`):
  1. `test_match_schema` - mocked LLM returns valid -> dataclass, 0<=score<=100.
  2. `test_match_clamps_score` - mocked 150 -> clamped 100; -5 -> 0.
  3. `test_match_handles_malformed_json` - mocked ```json fence + trailing text -> still parses.
  4. `test_match_empty_jd_raises` - empty JD -> `ValueError` friendly.
  5. `test_resume_read` - missing `main.tex` -> falls back to `main.tex.sample` with warning (not crash).
  6. Manual: run matcher on `fixtures/sample_main.tex` + `sample_job.json` -> `match.json` valid.

**Done when:** `match.json` always schema-valid, no crash on bad LLM output.

**Human steps:** 1 - paste Gemini key once (or Groq).

---

### PART 3 - Resume Tailor + Tectonic Compile + Self-Heal
**Depends:** Parts 0, 2.

**Build (`src/tailor.py`, `src/compiler.py`):**
- `tailor.py: tailor_resume(base_tex, job, match) -> str`: Prompt v2 rules: (a) inject `missing_skills` only where truthful/contextual, (b) rewrite summary/objective to job title, (c) preserve all LaTeX commands/environments, (d) escape `% & $ _ # { }` in inserted text only, (e) output full `.tex` only, no markdown. Save `[Company]_Resume.tex` (sanitized).
- `compiler.py: compile_tex(tex_path, timeout=120) -> pdf_path`: `shutil.which("tectonic")` check first with install hint if missing; `subprocess.run(["tectonic","-o",outdir,tex], capture_output, text)`. Non-zero -> raise `LatexCompileError(log)`.
- Self-heal (max 2 retries): on fail, call `llm.fix_latex(broken_tex, error_log)` prompt v3 ("fix only syntax, don't change content"), rewrite file, recompile. Log each attempt to `run.log`. If still failing, keep `.tex` + `.log` and print exact `tectonic` command for manual run; pipeline continues to Sheets logging with `PDF: FAILED`.
- Never overwrite `main.tex`.

**Testcases:**
- `test_tailor.py`:
  1. `test_tailor_preserves_commands` - mocked LLM output contains `\documentclass`, `\begin{document}`.
  2. `test_tailor_escapes_specials` - insert `R&D, 100%` -> `R\&D, 100\%` in output.
  3. `test_tailor_saves_file` - output path `output/.../<Company>_Resume.tex` exists.
- `test_compiler.py` (mock `subprocess.run` + `shutil.which`):
  4. `test_compile_success` - returncode 0 -> pdf path returned.
  5. `test_compile_missing_tectonic` - `which->None` -> error mentions `https://tectonic-typesetting.github.io` install.
  6. `test_self_heal_retries` - first call rc=1, fix returns good tex, second rc=0 -> 2 calls, pdf exists.
  7. `test_self_heal_gives_up_gracefully` - 3x rc=1 -> raises but preserves `.tex`+`.log`.
  8. Manual (if tectonic installed): compile `main.tex.sample` -> real PDF opens.

**Done when:** broken LLM LaTeX auto-recovers or fails with actionable log.

**Human steps:** 1 - install tectonic once (`winget install tectonic` / choco), `doctor` verifies.

---

### PART 4 - Google Sheets Tracking
**Depends:** Part 0. Integrable after Part 3.

**Build (`src/sheets.py`):**
- Auth: `credentials.json` (Desktop OAuth) + `token.json` reuse; scope `spreadsheets + drive.file`. First run opens browser, saves token. `--demo` uses in-memory fake sheet.
- `log_application(job, match, pdf_path, apply_url)`: opens sheet by `GOOGLE_SHEET_ID` (env), ensures header `["Date Applied","Company","Job Title","Match Score %","Local PDF Path","Application URL","Status","Last Email Date"]` (create if missing), appends row with today date, status=`Ready to Apply`. Returns row number.
- `get_tracked_companies(active_only=True)`: reads all rows, filters Status not in `["Rejected","Hired","Offer","Ready to Apply"→configurable? spec says exclude terminal + Ready to Apply for mail check]` - follow spec: skip `Rejected,Hired,Ready to Apply` for mail scan (make `TERMINAL_STATUSES` constant). Dedupe companies.
- `update_status(company, status, email_date)`: finds row by company (case-insensitive, latest), updates Status + Last Email Date.

**Testcases:**
- `test_sheets.py` (mock `gspread`):
  1. `test_log_appends_correct_columns` - fake sheet, assert 8-col row order + status `Ready to Apply`.
  2. `test_ensure_header` - empty sheet -> header created exactly once.
  3. `test_get_tracked_filters_terminal` - rows with Rejected/Hired skipped.
  4. `test_update_status_case_insensitive` - `acme` matches `Acme Inc`.
  5. `test_missing_sheet_id_raises` - friendly message with setup link.
  6. Manual: `python agent.py apply --demo` with real creds -> new row appears in Sheet.

**Done when:** demo + real sheet both log correctly, no duplicate headers.

**Human steps:** 2 (one-time): create Google Cloud Desktop-OAuth `credentials.json`, paste Sheet ID. Afterwards zero.

---

### PART 5 - Gmail Monitor + Classify
**Depends:** Parts 0, 2 (LLM), 4 (Sheets).

**Build (`src/gmail.py`):**
- Auth shared with Sheets (`token.json`). Gmail service `gmail/v1`.
- `check_mail(days=14, demo=False)`: for each tracked company from `get_tracked_companies()`, query `from OR subject:("{company}") newer_than:{days}d`, fetch max 10/msg (id, date, subject, snippet, body plain-text truncated 4000 chars). Skip already-processed `messageId`s (local `.seen_mail.json` in output/).
- Classify via `llm.complete_json` prompt v4 -> one of `["Rejection","Interview Invite","Assessment/Test","Offer","Marketing/Spam","Other"]` + confidence. Only update sheet if not `Marketing/Spam`/`Other` (or confidence <0.6 -> `Other`/skip). Update `Status` + `Last Email Date`.
- CLI: `python agent.py check-mail --days 14` prints table `Company | Subject | Date | → Status`. `--demo` uses `fixtures/sample_emails.json`.

**Testcases:**
- `test_gmail.py` (mock Gmail service + LLM + sheets):
  1. `test_rejection_classified` - body "we will not be moving forward" -> `Rejection`, sheet updated.
  2. `test_interview_classified` - "invite you to interview" -> `Interview Invite`.
  3. `test_spam_skipped` - "50% off courses" -> `Marketing/Spam`, sheet NOT updated.
  4. `test_seen_ids_skipped` - rerun same IDs -> 0 Gmail fetches.
  5. `test_truncates_long_body` - 50k body -> LLM gets <=4000 chars.
  6. `test_no_companies_no_crash` - empty sheet -> "nothing to check" message exit 0.
  7. Manual: real `check-mail --days 7` prints table, Sheet dates update.

**Done when:** reruns idempotent, spam never overwrites status.

**Human steps:** 0 after Part 4 (same OAuth).

---

### PART 6 - E2E Pipeline, Polish, Docs
**Depends:** Parts 0-5.

**Build (`src/pipeline.py`, README, final UX):**
- `run_apply(url, demo)`: doctor-lite -> parse+fetch job -> read resume -> match -> tailor -> compile (self-heal) -> log sheet -> print next-steps box:
  ```
  ✅ Done in 42s
  Match: 78% | PDF: output/Acme_4012/Acme_Resume.pdf
  Apply here: <apply_link>
  Logged to Sheet row 12 (Ready to Apply)
  Next: apply manually, then: python agent.py check-mail
  ```
  Exit codes: 0 ok, 2 config error, 3 job fetch error, 4 compile failed (with tex preserved).
- `--demo` end-to-end uses only fixtures, runnable with zero keys (primary acceptance test).
- Update `README.md`: 5-min quickstart, `.env` table, tectonic install (Windows winget), Google setup screenshots checklist, `doctor` output example, troubleshooting (401/tectonic/OAuth), demo command.
- `requirements.txt` freeze + `python -m pytest` green.

**Testcases:**
- `test_pipeline.py` (mock all externals):
  1. `test_demo_e2e` - `run_apply(demo=True)` creates `job.json, match.json, .tex, .pdf(fake), run.log` and fake sheet row.
  2. `test_pipeline_preserves_base_resume` - `main.tex` mtime/hash unchanged.
  3. `test_pipeline_continues_on_pdf_fail` - mocked compile fail -> still logs sheet with `PDF: FAILED`.
  4. `test_cli_routing` - bare URL routes to apply; `--check-mail` routes correctly.
  5. Full: `python -m pytest -q` all green + `python agent.py doctor` PASS.

**Done when:** fresh clone -> `pip install -r requirements.txt` -> `python agent.py --demo "<url>"` succeeds with no keys.

**Human steps:** 0 for demo; 3 one-time for real (keys + tectonic + Google).

---

## 4. Test Strategy (global)

- Framework: `pytest` + `pytest-mock`. No live API in tests (all `requests`, `llm`, `gspread`, `gmail`, `subprocess` mocked). Fixtures in `tests/fixtures/`.
- Commands:
  - `python -m pytest -q` (all)
  - `python -m pytest tests/test_job_api.py tests/test_matcher.py -q` (per-part)
  - `python agent.py doctor`
  - `python agent.py apply --demo "https://www.linkedin.com/jobs/view/4012345678"` (smoke)
  - `python agent.py check-mail --demo --days 7` (smoke)
- Coverage target: happy path + 1 failure path per module (auth fail, 429, bad JSON, missing tectonic, compile fail, spam mail).
- Manual checklist before "done": real URL -> real PDF opens -> Sheet row correct -> real `check-mail` classifies 1 rejection + 1 invite correctly.

## 5. Build Order for Agent (respect limits)

1. Part 0 alone (scaffold). Verify `doctor` + `--help`.
2. Part 1 alone. Verify mocked tests.
3. Part 2 alone. Verify `match.json`.
4. Part 3 alone. Verify compile + self-heal with mocks.
5. Part 4 alone. Verify with fake sheet.
6. Part 5 alone. Verify with fixtures.
7. Part 6 E2E + README. Verify `pytest` + demo E2E.

Do not combine parts in one diff. Stop after each part and run its tests.

## 6. Risks & Mitigations

- RapidAPI free-tier shape changes -> normalize multiple key aliases + log raw JSON; env-overridable endpoint/host.
- Gemini free quota/JSON fences -> `complete_json` strip + retry once; Groq fallback key optional.
- LLM breaks LaTeX -> self-heal loop (max 2) + preserve log; never overwrite base.
- Gmail OAuth friction -> `doctor` + `setup` wizard, `token.json` reuse, `--demo` bypass.
- Windows path/spaces in company names -> `sanitize_filename`, `subprocess` list-args (no shell).

## 7. Definition of Done

- [ ] `pip install -r requirements.txt` works on fresh Python 3.10+.
- [ ] `python agent.py doctor` PASS (or actionable FAIL).
- [ ] `python agent.py --demo "<any-url>"` creates PDF (or mocked PDF) + `match.json` + sheet row with zero keys.
- [ ] Real run: URL -> tailored PDF compiles via tectonic -> Sheet row `Ready to Apply` with correct apply link.
- [ ] `check-mail --demo` and real run update Status + Last Email Date, spam ignored, reruns idempotent.
- [ ] `python -m pytest -q` green (≥20 tests across 8 files).
- [ ] `main.tex` never modified; secrets gitignored; README quickstart accurate.

---
Next action: implement PART 0.
