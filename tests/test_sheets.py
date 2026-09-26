"""Part 4 tests: sheets log/header/filter/update (fake client)."""
from __future__ import annotations

import pytest

import src.sheets as S
from src.sheets import FakeClient, FakeWorksheet


class J:
    company = "Acme Corp"
    title = "Python Dev"
    apply_link = "https://apply/1"

class Mt:
    match_score = 82


def test_log_appends_correct_columns():
    c = FakeClient()
    row_no = S.log_application(J(), Mt(), "C:/out/R.pdf", "https://apply/1", "demo", client=c)
    vals = c.ws.get_all_values()
    assert vals[0] == S.HEADER
    row = vals[1]
    assert len(row) == 8
    assert row[1] == "Acme Corp" and row[6] == "Ready to Apply"
    assert row_no == 2


def test_ensure_header_once():
    ws = FakeWorksheet()
    S.ensure_header(ws)
    S.ensure_header(ws)
    assert ws.get_all_values()[0] == S.HEADER
    assert len(ws.get_all_values()) == 1


def test_get_tracked_filters_terminal():
    ws = FakeWorksheet()
    ws.rows = [S.HEADER,
               ["2026-01-01", "Acme", "T", "80", "p", "u", "Applied", ""],
               ["2026-01-01", "Bad", "T", "10", "p", "u", "Rejected", ""],
               ["2026-01-01", "HiredCo", "T", "90", "p", "u", "Hired", ""],
               ["2026-01-01", "NewCo", "T", "50", "p", "u", "Ready to Apply", ""]]
    c = FakeClient(ws)
    assert S.get_tracked_companies("demo", client=c) == ["Acme"]


def test_update_status_case_insensitive():
    ws = FakeWorksheet()
    ws.rows = [S.HEADER, ["2026-01-01", "Acme Inc", "T", "80", "p", "u", "Applied", ""]]
    c = FakeClient(ws)
    assert S.update_status("acme inc", "Interview Invite", "2026-09-23", "demo", client=c)
    assert ws.rows[1][6] == "Interview Invite"
    assert ws.rows[1][7] == "2026-09-23"


def test_missing_sheet_id_raises():
    with pytest.raises(S.SheetsError, match="GOOGLE_SHEET_ID"):
        S.log_application(J(), Mt(), "p", "u", "", client=None)
