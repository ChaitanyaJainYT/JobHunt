# JobHunt - Local Automated Job Application Assistant

Prepares a tailored LaTeX resume PDF for a job URL, logs to Google Sheets, and tracks Gmail replies. It never auto-applies - you apply manually with the logged link.

## 5-min quickstart

```bash
pip install -r requirements.txt
python agent.py doctor
python agent.py --demo "https://www.linkedin.com/jobs/view/4012345678"
python agent.py check-mail --demo --days 7
```

Real run (one-time setup, then one command per job):

```bash
python agent.py setup        # paste keys interactively
python agent.py "https://www.linkedin.com/jobs/view/4012345678"
python agent.py check-mail
```

## Web UI (easiest)

```bash
python agent.py ui
```

Opens `http://127.0.0.1:8765` (localhost only, no extra packages). Top to bottom: **New application** (paste URL → live progress → PDF + manual apply link), **Base resume** (`main.tex` editing — previous version auto-kept as `main.tex.bak`), **Check Gmail replies**, **Tracked applications** (direct **Open Google Sheet** link; per-row **edit icon** opens a `.tex` editor with **Save only** / **Save & compile PDF**, compile errors shown with the tectonic log), and a hidden-until-editing **resume editor** with **Raw TeX** and **Sections** modes (headers + contents as fields with add/delete/reorder; each section set to **Markdown**, **Plain text**, or **LaTeX** with auto-detection — Markdown supports `**bold**`, `*italic*`, `` `code` ``, `-`/`1.` (nested) lists, `[text](url)`, emitting only package-free LaTeX) plus **Preview PDF** (compiles current edits to a throwaway PDF inline before saving). Tracked rows can be **hidden (soft delete)** via the trash icon — folders and PDFs stay on disk and the Sheet row is untouched; restore anytime from “Show hidden”. A slim **left nav rail** toggles four minimized-by-default slide-in panels (opening one closes the others, `Esc` closes all): **Base resume** editor — the exact same Raw/Sections/Preview editor as tailored resumes, saving to `main.tex` with auto-`.bak` — **LinkedIn profile** editor, **Jobs** search (keyword + country over JSearch, ~1 RapidAPI call per search, one-click **Prepare** per result), and **Console** (`doctor`, `check-mail`, `apply`; never a shell; `setup` needs a real terminal). The main page itself stays lean: New application, Gmail replies, Tracked applications, resume editor. On narrow screens the rail becomes a bottom bar. LinkedIn blocks all embedding, so for LinkedIn postings use the panel's LinkedIn quick-links (new tab) and paste posting URLs back into New application. A **Dark/Light** toggle sits in the header (OS theme by default, choice remembered). Long jobs run in the background; Google consent tabs open in your browser as usual on first run.

## Commands

| Command | What it does |
|---|---|
| `python agent.py "<job-url>"` | Full flow: fetch job, match skills, tailor resume, compile PDF, log Sheet |
| `python agent.py apply --url "<url>" [--out DIR]` | Same as above (explicit) |
| `python agent.py check-mail [--days 14]` | Scan Gmail for tracked companies, update Sheet status |
| `python agent.py doctor` | Health check: Python, tectonic, .env, resume, Google creds, deps |
| `python agent.py setup` | Interactive `.env` wizard (asks only missing keys) |
| `--demo` / `--mock` | Offline trial with fixtures, no keys or network |

Exit codes: `0` ok, `2` config error, `3` fetch/match error, `4` PDF compile failed (tex preserved).

## .env keys

Copy `.env.example` to `.env` (auto-created) or run `setup`.

| Key | Required | Where to get |
|---|---|---|
| `GEMINI_API_KEY` (or `GROQ_API_KEY`) | yes (one) | https://aistudio.google.com/app/apikey |
| `GROQ_API_KEY` / `GROQ_MODEL` | no | Free at https://console.groq.com — auto-used when Gemini hits quota |
| `LINKEDIN_PROFILE_URL` | no | Your public LinkedIn profile URL (headline/about supplement) |
| `LINKEDIN_PROFILE_FILE` | no | Local supplement, default `profile.md` |
| `LLM_MODEL` | no | default `gemini-3.6-flash` |
| `RAPIDAPI_KEY` | yes | https://rapidapi.com, subscribe JSearch free tier |
| `RAPIDAPI_HOST` | no | default `jsearch.p.rapidapi.com` |
| `RAPIDAPI_JOB_ENDPOINT` | no | default `https://jsearch.p.rapidapi.com/job-details` |
| `RAPIDAPI_SEARCH_ENDPOINT` | no | default `https://jsearch.p.rapidapi.com/search-v2` |
| `RAPIDAPI_COUNTRY` | no | JSearch country bias, default `in` |
| `GOOGLE_SHEET_ID` | yes | from Sheet URL between `/d/` and `/edit` |
| `GOOGLE_CREDENTIALS_FILE` | no | default `credentials.json` (Desktop OAuth client) |

## Prereqs

1. Python 3.10+ (`python --version`).
2. Tectonic (LaTeX, zero-config): already bundled at `tools/tectonic/` — no install or PATH setup needed; the app finds it automatically (a system-wide `tectonic` on PATH is used if present instead). Verify with `python agent.py doctor`.
3. Your base resume as `main.tex` in project root (a `main.tex.sample` is bundled for trial).
4. Google (one-time): Google Cloud Console -> OAuth Desktop client -> download as `credentials.json`. First Sheets/Gmail run opens browser, saves `token.json` for later. All three are gitignored.

## LinkedIn skills in matching

`main.tex` stays the base, but anything in your LinkedIn profile also counts. Edit it right in the UI (**LinkedIn profile** card: editor + template loader, shows detected skill count on save) or copy `profile.md.example` to `profile.md` by hand and paste your LinkedIn About + Skills once. Every run merges it: the **match %** weighs resume + profile evidence (profile-only hits are listed separately as `profile_skills` in `match.json`), and the tailor may draw Skills-section entries from either source — never invented. Optionally set `LINKEDIN_PROFILE_URL` for headline/about context (public pages hide Skills, so the file is what matters). The UI shows the linked skill count under New application; each run audits what was used in `output/<job>/profile.json`.

## Honesty guard (no false skills)

Every tailored resume is verified skill-by-skill against your evidence (`main.tex` + profile): anything claimed without backing is first sent back to the LLM for a targeted removal pass, and anything surviving that is shown as a loud **HONESTY WARNING** (terminal + `run.log`) instead of shipping silently. The UI editor runs the same check on every save and flags unverified skills in amber. Word-boundary matching plus an alias table (`AWS` = `Amazon Web Services`, `Power BI` = `PowerBI`, `AI` ≠ the "ai" in "said") keep false alarms out.

## One listing, one folder

The same posting reached via LinkedIn URL and via JSearch search shares the LinkedIn ID in its apply link — runs detect that and **update the existing folder in place** instead of spawning `Company_X` + `Company_<token>` duplicates (hidden dupes stay restorable via “Show hidden”).

## How job fetching works

LinkedIn numeric IDs are not JSearch IDs, so for a LinkedIn URL the flow is: public page (title/company/description, free) → `/search-v2` text match → full `job-details` record (2 RapidAPI calls). Enrichment only attaches when the **company matches** (suffix-normalized) — a same-title role at another company is rejected and public data is kept. Non-LinkedIn hosts/IDs go straight to RapidAPI.

## Outputs

Per job: `output/<Company>_<JobId>/job.json`, `match.json`, `<COMPANY>_<Name>_Resume_<DDMMYY>.tex/.pdf`, `run.log`. Example: `HP_Chaitanya_Jain_Resume_230926.pdf` (name from `APPLICANT_NAME` in `.env`, date = run day). `main.tex` is never modified. Sheet columns: Date Applied, Company, Job Title, Match Score %, Local PDF Path, Application URL, Status (`Ready to Apply`), Last Email Date.

## Troubleshooting

- `401/403 RapidAPI`: key wrong or JSearch not subscribed -> RapidAPI dashboard -> `setup` again.
- `429 quota`: free tier exhausted -> wait/upgrade or `--demo`.
- `tectonic not found`: install above, reopen terminal, `doctor` must show PASS.
- `tectonic failed ... .log`: LLM broke LaTeX; agent auto-retries twice with fix prompt, else preserves `.tex` + `.tectonic.log` and still logs Sheet with `PDF: FAILED`. Manual: `tectonic --outdir <folder> <file>.tex`.
- `API key not valid (Gemini)`: `setup` again, check aistudio key.
- `LLM quota exceeded (429)`: free-tier budget hit. Small calls may still pass; big tailor calls fail first. Wait a few minutes and retry with `--resume` (reuses saved match, costs 1 call). For a permanent cushion, add a free `GROQ_API_KEY` (console.groq.com) — the app auto-falls-back to Groq on Gemini quota errors.
- `Missing GOOGLE_SHEET_ID` / OAuth: `doctor` shows exact fix; `--demo` bypasses.
- Browser shows `Access blocked: app has not completed verification` (Error 403: access_denied): your OAuth app is in Testing mode and your Gmail isn't a tester. Fix (one-time): Cloud Console -> your project -> APIs & Services -> OAuth consent screen -> Audience -> Test users -> Add users -> add your Gmail -> Save. Then re-run; no need to re-download credentials.json.
- Gmail spam overwriting status: never happens - `Marketing/Spam`/`Other`/low-confidence never update Sheet; reruns skip seen IDs via `output/.seen_mail.json`.

## Tests

```bash
python -m pytest -q
python -m pytest tests/test_job_api.py tests/test_matcher.py -q
```
All externals mocked (no network/keys). Manual smoke: real URL -> PDF opens -> Sheet row correct -> `check-mail` classifies 1 rejection + 1 invite.
