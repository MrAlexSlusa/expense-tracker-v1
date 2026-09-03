"""
Adds each expense to your personal budget spreadsheet using a service account
(not your personal Google login). Service accounts are the right tool here
because this runs unattended on a server with nobody around to click "allow"
on an OAuth prompt.

Unlike a plain expense log, this sheet has a fixed set of category rows
(Supermarket, Vodafone, Bolt / Uber, ...) with a running total in column D.
Texting "supermarket 50" doesn't add a new row - it finds the row whose
category name is the closest match (typos like "supermrket" still work) and
adds 50 to whatever total is already there. Matching is against the category
*names* only, not merchant names - "auchan 50" won't map to Supermarket, it
falls back to "Altele" since guessing wrong would silently misattribute the
expense.

Each month is its own spreadsheet file (e.g. "2026 Aug Budget"), not a tab
within one ongoing file - GOOGLE_SHEET_ID needs to be updated to that month's
file ID when a new one is created. This always writes to that file's first
sheet/tab.

If the credentials aren't configured or nothing matches well enough, this
fails quietly rather than breaking the webhook - a spreadsheet mirror going
down should never stop someone's expense from being logged in the real
database.
"""

import os
import json
import difflib
from dataclasses import dataclass
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


@dataclass
class SheetSyncResult:
    success: bool
    category: Optional[str] = None  # the sheet's actual category name, e.g. "Supermarket"
    reason: Optional[str] = None  # why it failed, for a human-readable WhatsApp reply

# Layout of the budget sheet's spending section.
CATEGORY_COLUMN = 3  # column C
AMOUNT_COLUMN = 4  # column D
FIRST_CATEGORY_ROW = 6
FALLBACK_CATEGORY_NAME = "Altele"
MATCH_CUTOFF = 0.7  # below this similarity, treat it as no match

_client = None
_client_init_attempted = False


def _get_client():
    global _client, _client_init_attempted

    if _client is not None:
        return _client
    if _client_init_attempted:
        return None  # already failed once this run; don't retry every message
    _client_init_attempted = True

    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        print("Google Sheets not configured (missing GOOGLE_SERVICE_ACCOUNT_JSON) - skipping sheet sync.")
        return None

    try:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        _client = gspread.authorize(creds)
        return _client
    except Exception as e:
        print(f"Google Sheets setup failed: {e}")
        return None


def _get_worksheet():
    client = _get_client()
    if client is None:
        return None

    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    if not sheet_id:
        print("Google Sheets not configured (missing GOOGLE_SHEET_ID) - skipping sheet sync.")
        return None

    try:
        return client.open_by_key(sheet_id).sheet1
    except Exception as e:
        print(f"Google Sheets setup failed: {e}")
        return None


def _list_category_rows(worksheet):
    """Returns [(row_number, category_name), ...] for the sheet's category rows."""
    values = worksheet.col_values(CATEGORY_COLUMN)
    rows = []
    row = FIRST_CATEGORY_ROW
    while row <= len(values):
        name = values[row - 1].strip()
        if not name:
            break
        rows.append((row, name))
        row += 1
    return rows


def _find_category_row(worksheet, category_word):
    """Returns (row_number, category_name) for the best match, or None."""
    rows = _list_category_rows(worksheet)
    if not rows:
        return None

    fallback = next((r for r in rows if r[1].lower() == FALLBACK_CATEGORY_NAME.lower()), None)

    if not category_word:
        return fallback

    names_lower = [name.lower() for _, name in rows]
    match = difflib.get_close_matches(category_word.lower(), names_lower, n=1, cutoff=MATCH_CUTOFF)
    if not match:
        return fallback

    matched_index = names_lower.index(match[0])
    return rows[matched_index]


def record_expense(category, amount: float) -> SheetSyncResult:
    worksheet = _get_worksheet()
    if worksheet is None:
        return SheetSyncResult(success=False, reason="Google Sheets isn't connected yet")

    match = _find_category_row(worksheet, category)
    if match is None:
        reason = "this month's tab has no category rows set up"
        print(f"Sheet sync skipped: {reason}.")
        return SheetSyncResult(success=False, reason=reason)

    row, matched_category = match
    try:
        current = worksheet.cell(row, AMOUNT_COLUMN, value_render_option="UNFORMATTED_VALUE").value or 0
        worksheet.update_cell(row, AMOUNT_COLUMN, float(current) + amount)
        return SheetSyncResult(success=True, category=matched_category)
    except Exception as e:
        print(f"Failed to update budget sheet: {e}")
        return SheetSyncResult(success=False, reason="couldn't write to the sheet")
