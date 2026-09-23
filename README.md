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
| `LLM_MODEL` | no | default `gemini-3.6-flash` |
| `RAPIDAPI_KEY` | yes | https://rapidapi.com, subscribe JSearch free tier |
| `RAPIDAPI_HOST` | no | default `jsearch.p.rapidapi.com` |
| `RAPIDAPI_JOB_ENDPOINT` | no | default `https://jsearch.p.rapidapi.com/job-details` |
| `GOOGLE_SHEET_ID` | yes | from Sheet URL between `/d/` and `/edit` |
| `GOOGLE_CREDENTIALS_FILE` | no | default `credentials.json` (Desktop OAuth client) |

## Prereqs

1. Python 3.10+ (`python --version`).
2. Tectonic (LaTeX, zero-config): Windows `winget install tectonic`, then reopen terminal. Verify with `python agent.py doctor`.
3. Your base resume as `main.tex` in project root (a `main.tex.sample` is bundled for trial).
4. Google (one-time): Google Cloud Console -> OAuth Desktop client -> download as `credentials.json`. First Sheets/Gmail run opens browser, saves `token.json` for later. All three are gitignored.

## Outputs

Per job: `output/<Company>_<JobId>/job.json`, `match.json`, `<Company>_Resume.tex`, `<Company>_Resume.pdf`, `run.log`. `main.tex` is never modified. Sheet columns: Date Applied, Company, Job Title, Match Score %, Local PDF Path, Application URL, Status (`Ready to Apply`), Last Email Date.

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
