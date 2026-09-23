"""Google Sheets tracking. Real via gspread+OAuth, demo/tests via FakeWorksheet.

Columns: Date Applied | Company | Job Title | Match Score % | Local PDF Path
         | Application URL | Status | Last Email Date
Default status: "Ready to Apply".
Mail scan skips: Rejected, Hired, Offer, Ready to Apply (per spec).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

HEADER = ["Date Applied", "Company", "Job Title", "Match Score %",
          "Local PDF Path", "Application URL", "Status", "Last Email Date"]
DEFAULT_STATUS = "Ready to Apply"
SKIP_FOR_MAIL = {"rejected", "hired", "offer", "ready to apply"}


class SheetsError(Exception):
    pass


# ---- In-memory fake (demo + tests) ----
class FakeWorksheet:
    def __init__(self):
        self.rows: list[list[str]] = []

    def get_all_values(self):
        return [list(r) for r in self.rows]

    def append_row(self, row, value_input_option="USER_ENTERED"):
        self.rows.append([str(x) for x in row])
        return {"updates": {"updatedRows": 1}}

    def update_cell(self, r: int, c: int, v: str):
        self.rows[r - 1][c - 1] = str(v)

    def find_row_by_company(self, company: str) -> int | None:
        target = company.strip().lower()
        found = None
        for i, r in enumerate(self.rows[1:], start=2):
            if len(r) > 1 and r[1].strip().lower() == target:
                found = i  # latest match wins
        return found


class FakeClient:
    def __init__(self, ws: FakeWorksheet | None = None):
        self.ws = ws or FakeWorksheet()
    def open_by_key(self, _key: str):
        c = self
        class S:
            @property
            def sheet1(self):
                return c.ws
        return S()


def ensure_header(ws) -> None:
    vals = ws.get_all_values()
    if not vals:
        ws.append_row(HEADER)
    elif [str(x).strip() for x in vals[0]] != HEADER:
        # header missing/mismatched and sheet empty-ish -> prepend if only data?
        if not vals[0] or vals[0][0] == "":
            ws.rows.insert(0, list(HEADER)) if hasattr(ws, "rows") else ws.append_row(HEADER)


def load_valid_creds(tok_path: Path, scopes: list[str]):
    """Load cached creds when usable without a browser popup.

    Returns creds if the stored token covers all scopes AND is either valid
    or refreshable (expired access token + refresh token -> silent refresh).
    Returns None when interactive re-consent is genuinely needed.

    Both Credentials.valid and from_authorized_user_file() ignore the scopes
    actually granted to the stored token, so without a file-level check a
    Sheets-only token would be silently reused for Gmail -> 403.
    """
    import json
    from google.oauth2.credentials import Credentials
    if not tok_path.exists():
        return None
    try:
        granted = set(json.loads(tok_path.read_text(encoding="utf-8")).get("scopes", []) or [])
    except Exception:
        return None
    if not set(scopes) <= granted:
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(tok_path), scopes)
    except Exception:
        return None
    if not creds:
        return None
    if creds.valid or (creds.expired and creds.refresh_token):
        return creds
    return None


SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
                 "https://www.googleapis.com/auth/drive.file"]
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
# One combined consent for the whole app: a single refresh-token lineage
# covering everything. Separate per-flow consents overwrite each other's
# refresh tokens, leaving a token file whose scope list is a lie.
APP_SCOPES = SHEETS_SCOPES + GMAIL_SCOPES


def _try_refresh(creds) -> bool:
    """Silent refresh. False (never raises) when the stored grant can't
    refresh (revoked / scope mismatch) so callers can fall back to browser."""
    from google.auth.transport.requests import Request
    try:
        creds.refresh(Request())
        return True
    except Exception:
        return False


def _browser_consent(cred_path: Path, error_cls):
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not cred_path.exists():
        raise error_cls(
            f"Google credentials not found: {cred_path}. Create Desktop-OAuth "
            "client in Google Cloud Console, download as credentials.json.")
    flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), APP_SCOPES)
    return flow.run_local_server(port=0)


def _open_worksheet(sheet_id: str, creds_file: str, client=None):
    if client is not None:
        return client.open_by_key(sheet_id).sheet1
    if not sheet_id or sheet_id == "demo":
        raise SheetsError("Missing GOOGLE_SHEET_ID. Fix: python agent.py setup (paste Sheet ID from URL).")
    try:
        import gspread
        from oauth2client.service_account import ServiceAccountCredentials  # fallback
    except ImportError as e:
        raise SheetsError("gspread not installed. Run: pip install -r requirements.txt") from e
    # Prefer OAuth desktop flow (personal Gmail) with token reuse.
    # All consents request APP_SCOPES so one refresh-token lineage covers
    # Sheets + Gmail (per-flow consents clobber each other's grants).
    try:
        from google.oauth2.credentials import Credentials  # noqa: F401 (re-exported)
        root = Path(__file__).resolve().parent.parent
        cred_path = root / creds_file if not Path(creds_file).is_absolute() else Path(creds_file)
        tok_path = root / "token.json"
        creds = load_valid_creds(tok_path, SHEETS_SCOPES)
        if creds and not creds.valid:
            if not (creds.refresh_token and _try_refresh(creds)):
                creds = None
        if not creds:
            print("[INFO] Opening browser for Google consent (one-time)...")
            creds = _browser_consent(cred_path, SheetsError)
            save_token_merged(tok_path, creds)
        gc = gspread.authorize(creds)
        try:
            return gc.open_by_key(sheet_id).sheet1
        except Exception as e:
            # A still-valid access token may predate the latest consent and
            # lack the new scopes. Refresh once (mints a token with the full
            # granted set) and retry; if refresh itself fails, re-consent.
            if _is_scope_error(e) and getattr(creds, "refresh_token", None):
                if _try_refresh(creds):
                    save_token_merged(tok_path, creds)
                    return gspread.authorize(creds).open_by_key(sheet_id).sheet1
                print("[INFO] Stored grant can't refresh; opening browser...")
                creds = _browser_consent(cred_path, SheetsError)
                save_token_merged(tok_path, creds)
                return gspread.authorize(creds).open_by_key(sheet_id).sheet1
            raise
    except SheetsError:
        raise
    except Exception as e:
        detail = f"{e} (caused by {e.__cause__})" if str(e) == "" and e.__cause__ else str(e)
        raise SheetsError(f"Sheets auth/open failed: {detail}. {oauth_denied_hint(detail)}"
                          "Run 'python agent.py doctor'.") from e


def _is_scope_error(e: Exception) -> bool:
    seen, visited = e, set()
    while seen is not None and id(seen) not in visited:
        visited.add(id(seen))
        if "insufficient authentication scopes" in str(seen).lower():
            return True
        seen = seen.__cause__ if seen.__cause__ is not None else seen.__context__
    return False


def save_token_merged(tok_path: Path, creds) -> None:
    """Persist creds, UNIONING scopes with any previously stored ones.

    Each OAuth consent only lists its own scopes; a naive overwrite would
    drop the other flow's scopes and force an endless re-consent ping-pong
    (the refresh token itself accumulates all granted scopes server-side).
    """
    import json
    prev_scopes: set[str] = set()
    try:
        if tok_path.exists():
            prev_scopes = set(json.loads(tok_path.read_text(encoding="utf-8")).get("scopes", []) or [])
    except Exception:
        pass
    try:
        data = json.loads(creds.to_json())
    except Exception:
        tok_path.write_text(creds.to_json(), encoding="utf-8")
        return
    data["scopes"] = sorted(prev_scopes | set(data.get("scopes", []) or []))
    tok_path.write_text(json.dumps(data), encoding="utf-8")


def oauth_denied_hint(msg: str) -> str:
    """Guidance for the 'app not verified / access_denied' testing-mode block."""
    if "access_denied" in msg.lower() or "verification" in msg.lower():
        return ("If the browser showed 'Access blocked: app has not completed the Google "
                "verification process' (Error 403: access_denied), your OAuth app is in Testing "
                "mode and your Gmail is not listed as a tester. Fix (2 min, one-time): Google Cloud "
                "Console -> your project -> APIs & Services -> OAuth consent screen -> Audience -> "
                "under 'Test users' click 'Add users' -> add your Gmail address -> Save. Then re-run. ")
    return ""


def log_application(job, match, pdf_path: str, apply_url: str,
                    sheet_id: str, creds_file: str = "credentials.json",
                    client=None) -> int:
    ws = _open_worksheet(sheet_id, creds_file, client)
    ensure_header(ws)
    row = [date.today().isoformat(), getattr(job, "company", ""), getattr(job, "title", ""),
           getattr(match, "match_score", ""), pdf_path, apply_url or getattr(job, "apply_link", ""),
           DEFAULT_STATUS, ""]
    ws.append_row(row)
    vals = ws.get_all_values()
    return len(vals)  # 1-based row number


def get_tracked_companies(sheet_id: str, creds_file: str = "credentials.json",
                          client=None) -> list[str]:
    ws = _open_worksheet(sheet_id, creds_file, client)
    vals = ws.get_all_values()
    if len(vals) < 2:
        return []
    idx_company = 1
    idx_status = 6
    seen: list[str] = []
    for r in vals[1:]:
        if len(r) <= idx_company:
            continue
        comp = r[idx_company].strip()
        status = r[idx_status].strip().lower() if len(r) > idx_status else ""
        if not comp or status in SKIP_FOR_MAIL or comp in seen:
            continue
        seen.append(comp)
    return seen


def update_status(company: str, status: str, email_date: str,
                  sheet_id: str, creds_file: str = "credentials.json",
                  client=None) -> bool:
    ws = _open_worksheet(sheet_id, creds_file, client)
    vals = ws.get_all_values()
    target = company.strip().lower()
    found = None
    for i, r in enumerate(vals[1:], start=2):
        if len(r) > 1 and r[1].strip().lower() == target:
            found = i
    if not found:
        return False
    ws.update_cell(found, 7, status)
    ws.update_cell(found, 8, email_date)
    return True
