"""Gmail monitor: search tracked companies, classify, update sheet.

Labels: Rejection | Interview Invite | Assessment/Test | Offer | Marketing/Spam | Other
Spam/Other or confidence<0.6 never overwrite sheet. Reruns idempotent via seen IDs.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path

from src import llm

LABELS = ["Rejection", "Interview Invite", "Assessment/Test", "Offer", "Marketing/Spam", "Other"]
SKIP_LABELS = {"Marketing/Spam", "Other"}
CLASSIFY_PROMPT_V4 = """Classify this employer email into EXACTLY one label: {labels}.
Return VALID JSON only: {{"label": str, "confidence": 0.0-1.0}}
Rules: rejection phrases ("not moving forward", "decided to pursue other") -> Rejection. Interview invite/schedule -> Interview Invite. Online test/assessment/hackerrank -> Assessment/Test. Offer letter/compensation -> Offer. Courses/ads/unrelated -> Marketing/Spam. Else Other.

SUBJECT: {subject}
BODY (truncated):
{body}
"""

SEEN_DEFAULT = Path(__file__).resolve().parent.parent / "output" / ".seen_mail.json"


class GmailError(Exception):
    pass


@dataclass
class Email:
    msg_id: str
    company: str
    subject: str
    date: str
    body: str


def classify_email(subject: str, body: str, api_key: str = "",
                   model: str = "gemini-3.6-flash", groq_key: str = "",
                   groq_model: str = "openai/gpt-oss-120b") -> tuple[str, float]:
    data = llm.complete_json(
        CLASSIFY_PROMPT_V4.format(labels="/".join(LABELS),
                                  subject=subject[:300], body=body[:4000]),
        api_key=api_key, model=model, groq_key=groq_key, groq_model=groq_model)
    label = str(data.get("label", "Other")).strip()
    if label not in LABELS:
        # fuzzy match
        low = label.lower()
        for L in LABELS:
            if L.lower() in low or low in L.lower():
                label = L
                break
        else:
            label = "Other"
    try:
        conf = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    return label, max(0.0, min(1.0, conf))


def load_seen(path: Path) -> set[str]:
    try:
        return set(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return set()


def save_seen(seen: set[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(seen)), encoding="utf-8")


def _real_search(service, company: str, days: int, max_n: int = 10) -> list[dict]:
    q = f'"{company}" newer_than:{days}d'
    resp = service.users().messages().list(userId="me", q=q, maxResults=max_n).execute()
    return resp.get("messages", [])


def _real_get(service, msg_id: str) -> tuple[str, str, str]:
    m = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    headers = {h["name"].lower(): h["value"]
               for h in m.get("payload", {}).get("headers", [])}
    subject = headers.get("subject", "")
    date = headers.get("date", "")
    body = ""
    def walk(part):
        nonlocal body
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data", "")
        if data and ("text/plain" in mime or "text/html" in mime):
            try:
                body += base64.urlsafe_b64decode(data).decode("utf-8", "ignore") + "\n"
            except Exception:
                pass
        for p in part.get("parts", []):
            walk(p)
    walk(m.get("payload", {}))
    return subject, date, body[:8000]


def build_gmail_service(creds_file: str = "credentials.json"):
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as e:
        raise GmailError("Gmail libs missing. Run: pip install -r requirements.txt") from e
    from src.sheets import oauth_denied_hint
    scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
    root = Path(__file__).resolve().parent.parent
    cred_path = root / creds_file if not Path(creds_file).is_absolute() else Path(creds_file)
    tok_path = root / "token.json"
    from src.sheets import load_valid_creds
    try:
        creds = load_valid_creds(tok_path, scopes)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not cred_path.exists():
                    raise GmailError(f"Google credentials not found: {cred_path}.")
                flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), scopes)
                creds = flow.run_local_server(port=0)
            # merge scopes with any previously stored ones (see save_token_merged)
            from src.sheets import save_token_merged
            save_token_merged(tok_path, creds)
        return build("gmail", "v1", credentials=creds)
    except GmailError:
        raise
    except Exception as e:
        raise GmailError(f"Gmail auth failed: {e}. {oauth_denied_hint(str(e))}") from e


def run_check_mail(companies: list[str], sheet_id: str, creds_file: str = "credentials.json",
                   days: int = 14, api_key: str = "", model: str = "gemini-3.6-flash",
                   groq_key: str = "", groq_model: str = "openai/gpt-oss-120b",
                   seen_path: Path = SEEN_DEFAULT,
                   email_fetcher=None, service=None, sheet_client=None) -> list[dict]:
    """Fetch+classify+update. Returns per-email result dicts. Testable via email_fetcher."""
    from src import sheets
    if not companies:
        print("[MAIL] Nothing to check: no tracked companies (all terminal or empty sheet).")
        return []
    seen = load_seen(seen_path)
    if service is None and email_fetcher is None:
        service = build_gmail_service(creds_file)
    results: list[dict] = []
    for company in companies:
        if email_fetcher is not None:
            emails: list[Email] = email_fetcher(company) or []
        else:
            emails = []
            assert service is not None
            for meta in _real_search(service, company, days):
                mid = meta.get("id", "")
                if not mid or mid in seen:
                    continue
                subj, dt, body = _real_get(service, mid)
                emails.append(Email(mid, company, subj, dt, body))
        for em in emails:
            if em.msg_id in seen:
                continue
            seen.add(em.msg_id)
            label, conf = classify_email(em.subject, em.body, api_key, model,
                                           groq_key, groq_model)
            updated = False
            if label not in SKIP_LABELS and conf >= 0.6:
                try:
                    updated = sheets.update_status(company, label, em.date,
                                                   sheet_id, creds_file, client=sheet_client)
                except Exception as e:
                    print(f"[WARN] Sheet update skipped ({company}): {e}")
                    updated = False
            results.append({"company": company, "subject": em.subject, "date": em.date,
                            "label": label, "confidence": conf, "updated": updated})
            arrow = "-> " + label if updated else f"({label}, skipped)" if label in SKIP_LABELS else f"({label} low-conf)"
            print(f"{company} | {em.subject[:60]} | {em.date} {arrow}")
    save_seen(seen, seen_path)
    if not results:
        print("[MAIL] No new employer emails found.")
    return results
