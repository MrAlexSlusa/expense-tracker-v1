"""
Exchange rates: parsing BNR's XML, converting with it, and logging an expense
in a currency that isn't the account's.

Nothing here touches the network. The XML sample below is a trimmed copy of a
real response, and every test that needs rates points app.bnr at a temporary
folder - a test suite that depended on BNR being up (or on today's rate) would
fail for reasons that have nothing to do with this code.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import bnr
from app.database import Base, get_db
from app.main import app
from app.parser import parse_expense_message

TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


# A real response, cut down to the currencies that matter here. HUF is kept
# because it carries the multiplier attribute, which is the one part of the
# format that is easy to get silently wrong.
SAMPLE_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<DataSet xmlns="https://www.bnr.ro/xsd">
  <Header><Publisher>National Bank of Romania</Publisher><PublishingDate>2026-09-04</PublishingDate></Header>
  <Body>
    <Subject>Reference rates</Subject>
    <OrigCurrency>RON</OrigCurrency>
    <Cube date="2026-09-04">
      <Rate currency="EUR">5.2524</Rate>
      <Rate currency="USD">4.5199</Rate>
      <Rate currency="GBP">6.1135</Rate>
      <Rate currency="HUF" multiplier="100">1.4464</Rate>
    </Cube>
  </Body>
</DataSet>
"""


def make_snapshot(published: date | None = None) -> dict:
    parsed = bnr.parse_bnr_xml(SAMPLE_XML)
    if published is not None:
        parsed["date"] = published.isoformat()
    return {
        "date": parsed["date"],
        "base": "RON",
        "rates": parsed["rates"],
        "crypto": {"BTC": {"ron": 361686.92, "usd": 80021.0}, "ETH": {"ron": 11320.09, "usd": 2504.5}},
    }


@pytest.fixture
def rates_dir(tmp_path, monkeypatch):
    """Points app.bnr at a throwaway folder holding one fresh snapshot."""
    monkeypatch.setattr(bnr, "RATES_DIR", tmp_path)
    bnr.save_snapshot(make_snapshot(date.today()), directory=tmp_path)
    # Any live fetch would be a bug in these tests, so make it loud rather
    # than letting a missed code path quietly reach the internet.
    monkeypatch.setattr(bnr, "_http_get", lambda url: pytest.fail(f"unexpected network call to {url}"))
    monkeypatch.setattr(bnr, "_live_cache", None)
    monkeypatch.setattr(bnr, "_live_cache_at", None)
    return tmp_path


# --- parsing ---------------------------------------------------------------


def test_parse_bnr_xml_reads_the_banking_date_and_rates():
    parsed = bnr.parse_bnr_xml(SAMPLE_XML)
    assert parsed["date"] == "2026-09-04"
    assert parsed["rates"]["EUR"] == 5.2524
    assert parsed["rates"]["RON"] == 1.0


def test_parse_bnr_xml_normalises_the_multiplier():
    # 100 HUF = 1.4464 RON, so one HUF is a hundredth of that. Getting this
    # wrong would price a forint like a euro.
    rates = bnr.parse_bnr_xml(SAMPLE_XML)["rates"]
    assert rates["HUF"] == pytest.approx(0.014464)


def test_parse_bnr_xml_rejects_a_response_that_is_not_the_feed():
    with pytest.raises(ValueError):
        bnr.parse_bnr_xml(b"<html><body>BNR homepage</body></html>")


# --- snapshots on disk -----------------------------------------------------


def test_save_and_load_snapshot_round_trip(tmp_path):
    bnr.save_snapshot(make_snapshot(date(2026, 9, 4)), directory=tmp_path)
    assert (tmp_path / "2026-09-04.json").is_file()
    assert (tmp_path / "latest.json").is_file()

    loaded = bnr.load_snapshot(tmp_path)
    assert loaded["date"] == "2026-09-04"
    assert loaded["rates"]["EUR"] == 5.2524


def test_load_snapshot_falls_back_to_the_newest_dated_file(tmp_path):
    bnr.save_snapshot(make_snapshot(date(2026, 8, 28)), directory=tmp_path)
    bnr.save_snapshot(make_snapshot(date(2026, 9, 4)), directory=tmp_path)
    (tmp_path / "latest.json").unlink()

    assert bnr.load_snapshot(tmp_path)["date"] == "2026-09-04"


def test_load_snapshot_skips_a_corrupt_file(tmp_path):
    bnr.save_snapshot(make_snapshot(date(2026, 9, 4)), directory=tmp_path)
    (tmp_path / "latest.json").write_text("{ truncated", encoding="utf-8")

    # The dated file beside it is still good, so a half-written latest.json
    # costs nothing.
    assert bnr.load_snapshot(tmp_path)["date"] == "2026-09-04"


def test_load_snapshot_returns_none_for_an_empty_folder(tmp_path):
    assert bnr.load_snapshot(tmp_path) is None


# --- the automation's spreadsheet ------------------------------------------
# A scheduled job drops an .xlsx in the folder every Monday. These cover the
# shape it actually writes, plus the ways a spreadsheet can drift.


def write_sheet(path: Path, rows, header=("Monedă", "Curs (RON)", "Dată")):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Curs BNR"
    if header:
        ws.append(list(header))
    for row in rows:
        ws.append(list(row))
    wb.save(path)
    return path


SHEET_ROWS = [
    ("EUR", 5.2524, "06.09.2026"),
    ("USD", 4.5199, "06.09.2026"),
    ("GBP", 6.1135, "06.09.2026"),
    ("BTC", 360893.63, "06.09.2026"),
    ("ETH", 11212.38, "06.09.2026"),
]


def test_reads_the_automations_spreadsheet(tmp_path):
    path = write_sheet(tmp_path / "Curs BNR 06.09.2026.xlsx", SHEET_ROWS)
    snapshot = bnr.read_xlsx_snapshot(path)

    assert snapshot["date"] == "2026-09-06"  # DD.MM.YYYY in the sheet, ISO in the snapshot
    assert snapshot["rates"] == {"RON": 1.0, "EUR": 5.2524, "USD": 4.5199, "GBP": 6.1135}
    # Crypto is split out from fiat, so the rates page can still say which is which.
    assert snapshot["crypto"]["BTC"]["ron"] == 360893.63
    assert "BTC" not in snapshot["rates"]


def test_spreadsheet_header_row_is_not_read_as_a_currency(tmp_path):
    path = write_sheet(tmp_path / "Curs BNR 06.09.2026.xlsx", SHEET_ROWS)
    snapshot = bnr.read_xlsx_snapshot(path)
    assert "MONEDĂ" not in snapshot["rates"]
    assert len(snapshot["rates"]) == 4  # RON + the three fiat rows


def test_spreadsheet_dates_the_snapshot_from_its_filename_when_the_column_is_missing(tmp_path):
    path = write_sheet(tmp_path / "Curs BNR 06.09.2026.xlsx", [("EUR", 5.2524), ("USD", 4.5199)], header=None)
    assert bnr.read_xlsx_snapshot(path)["date"] == "2026-09-06"


def test_an_unreadable_spreadsheet_is_skipped_rather_than_raising(tmp_path):
    path = tmp_path / "Curs BNR 06.09.2026.xlsx"
    path.write_bytes(b"not a spreadsheet")
    assert bnr.read_xlsx_snapshot(path) is None


def test_a_spreadsheet_with_no_currency_rows_is_not_a_snapshot(tmp_path):
    path = write_sheet(tmp_path / "Curs BNR 06.09.2026.xlsx", [("total", None, "")])
    assert bnr.read_xlsx_snapshot(path) is None


def test_the_newest_file_wins_across_both_formats(tmp_path):
    # The two naming conventions don't sort against each other, so this is
    # ordered by the date each filename carries, not by the filename itself.
    bnr.save_snapshot(make_snapshot(date(2026, 9, 4)), directory=tmp_path)
    write_sheet(tmp_path / "Curs BNR 06.09.2026.xlsx", SHEET_ROWS)

    loaded = bnr.load_snapshot(tmp_path)
    assert loaded["date"] == "2026-09-06"
    assert loaded["source"] == "Curs BNR 06.09.2026.xlsx"


def test_an_older_spreadsheet_loses_to_a_newer_json(tmp_path):
    write_sheet(tmp_path / "Curs BNR 28.08.2026.xlsx", SHEET_ROWS)
    bnr.save_snapshot(make_snapshot(date(2026, 9, 4)), directory=tmp_path)

    assert bnr.load_snapshot(tmp_path)["date"] == "2026-09-04"


def test_excel_lock_files_are_ignored(tmp_path):
    # Opening the sheet in Excel leaves a "~$" stub beside it that is not a
    # workbook; reading it would fail and, worse, could win on date order.
    write_sheet(tmp_path / "Curs BNR 06.09.2026.xlsx", SHEET_ROWS)
    (tmp_path / "~$Curs BNR 06.09.2026.xlsx").write_bytes(b"lock")

    assert bnr.load_snapshot(tmp_path)["date"] == "2026-09-06"


def test_expenses_convert_from_the_spreadsheet(tmp_path, monkeypatch):
    monkeypatch.setattr(bnr, "RATES_DIR", tmp_path)
    write_sheet(tmp_path / f"Curs BNR {date.today().strftime('%d.%m.%Y')}.xlsx", SHEET_ROWS)
    monkeypatch.setattr(bnr, "_http_get", lambda url: pytest.fail(f"unexpected network call to {url}"))

    token = _signup("sheet@example.com")
    _set_currency(token, "RON")
    body = client.post("/api/expenses", headers=_auth(token), json={"amount": 25, "currency": "EUR"}).json()

    assert body["amount"] == pytest.approx(131.31)
    assert body["original_currency"] == "EUR"


def test_a_snapshot_older_than_the_window_is_stale():
    fresh = make_snapshot(date.today() - timedelta(days=3))
    old = make_snapshot(date.today() - timedelta(days=bnr.MAX_SNAPSHOT_AGE_DAYS + 1))
    assert not bnr.is_stale(fresh)
    assert bnr.is_stale(old)


def test_get_snapshot_serves_stale_rates_rather_than_failing(tmp_path, monkeypatch):
    monkeypatch.setattr(bnr, "RATES_DIR", tmp_path)
    bnr.save_snapshot(make_snapshot(date.today() - timedelta(days=90)), directory=tmp_path)

    # Old rates convert to within a percent or so; refusing outright would
    # block logging an expense entirely, which is worse.
    snapshot = bnr.get_snapshot(allow_live=False)
    assert snapshot["stale"] is True
    assert snapshot["age_days"] == 90
    assert snapshot["rates"]["EUR"] == 5.2524


def test_get_snapshot_raises_when_there_is_nothing_at_all(tmp_path, monkeypatch):
    monkeypatch.setattr(bnr, "RATES_DIR", tmp_path)
    with pytest.raises(bnr.RatesUnavailable):
        bnr.get_snapshot(allow_live=False)


# --- conversion ------------------------------------------------------------


def test_convert_to_ron_uses_the_reference_rate():
    amount, rate = bnr.convert(100, "EUR", "RON", make_snapshot())
    assert rate == pytest.approx(5.2524)
    assert amount == pytest.approx(525.24)


def test_convert_between_two_foreign_currencies_goes_through_ron():
    amount, rate = bnr.convert(100, "EUR", "USD", make_snapshot())
    assert rate == pytest.approx(5.2524 / 4.5199)
    assert amount == pytest.approx(116.2, abs=0.05)


def test_convert_is_a_no_op_for_the_same_currency():
    assert bnr.convert(42.5, "EUR", "EUR", make_snapshot()) == (42.5, 1.0)


def test_convert_prices_crypto_through_its_ron_value():
    amount, _ = bnr.convert(1, "BTC", "RON", make_snapshot())
    assert amount == pytest.approx(361686.92)


def test_convert_rejects_a_currency_bnr_does_not_publish():
    with pytest.raises(KeyError):
        bnr.convert(10, "XYZ", "RON", make_snapshot())


def test_page_rates_labels_each_row_with_its_source():
    page = bnr.page_rates(make_snapshot(date(2026, 9, 4)))
    by_code = {row["currency"]: row for row in page["rates"]}

    assert [row["currency"] for row in page["rates"]] == ["EUR", "USD", "GBP", "BTC", "ETH"]
    assert by_code["EUR"]["source"] == "bnr"
    # The central bank publishes no crypto rate, and the page must not imply
    # otherwise - this label is what the UI prints under the row.
    assert by_code["BTC"]["source"] == "crypto"
    assert by_code["BTC"]["kind"] == "crypto"
    assert page["date"] == "2026-09-04"


# --- the parser ------------------------------------------------------------


@pytest.mark.parametrize("text,expected", [
    ("50 eur benzina", "EUR"),
    ("spent 100 usd on groceries", "USD"),
    ("gbp 40 books", "GBP"),
    ("25,50 lei cafea", "RON"),
    ("120 mancare", None),  # no currency word: the account's own is implied
])
def test_parser_picks_up_a_currency_when_one_is_named(text, expected):
    assert parse_expense_message(text).currency == expected


def test_parser_keeps_the_currency_word_out_of_the_category():
    parsed = parse_expense_message("50 eur benzina")
    assert parsed.category == "benzina"
    assert parsed.amount == 50.0


# --- the API ---------------------------------------------------------------


def _signup(email: str, password="hunter2222") -> str:
    r = client.post("/api/auth/signup", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _set_currency(token, code):
    assert client.put("/api/me/currency", headers=_auth(token), json={"currency": code}).status_code == 200


def test_rates_endpoint_returns_the_five_shown_currencies(rates_dir):
    body = client.get("/api/rates").json()
    assert [row["currency"] for row in body["rates"]] == ["EUR", "USD", "GBP", "BTC", "ETH"]
    assert body["base"] == "RON"
    assert body["stale"] is False


def test_rates_endpoint_reports_when_rates_cannot_be_had(tmp_path, monkeypatch):
    monkeypatch.setattr(bnr, "RATES_DIR", tmp_path)
    monkeypatch.setattr(bnr, "_live_snapshot", lambda: None)
    assert client.get("/api/rates").status_code == 503


def test_convert_endpoint(rates_dir):
    body = client.get("/api/rates/convert", params={"amount": 100, "source": "EUR", "target": "RON"}).json()
    assert body["amount"] == pytest.approx(525.24)
    assert body["target"] == "RON"


def test_expense_in_a_foreign_currency_is_stored_in_the_users_own(rates_dir):
    token = _signup("fx@example.com")
    _set_currency(token, "RON")

    r = client.post("/api/expenses", headers=_auth(token), json={"amount": 25, "currency": "EUR"})
    assert r.status_code == 200, r.text
    body = r.json()

    # The stored amount is in lei - every total in the app sums this column,
    # so a euro left in it would corrupt the month.
    assert body["amount"] == pytest.approx(131.31)
    assert body["original_amount"] == 25
    assert body["original_currency"] == "EUR"
    assert body["fx_rate"] == pytest.approx(5.2524)


def test_expense_in_the_users_own_currency_records_no_conversion(rates_dir):
    token = _signup("same@example.com")
    _set_currency(token, "RON")

    body = client.post("/api/expenses", headers=_auth(token), json={"amount": 25, "currency": "RON"}).json()
    assert body["amount"] == 25
    # Indistinguishable from an expense logged before any of this existed.
    assert body["original_currency"] is None
    assert body["fx_rate"] is None


def test_expense_without_a_currency_is_unchanged(rates_dir):
    token = _signup("plain@example.com")
    _set_currency(token, "RON")

    body = client.post("/api/expenses", headers=_auth(token), json={"amount": 25}).json()
    assert body["amount"] == 25
    assert body["original_currency"] is None


def test_a_foreign_expense_counts_towards_the_monthly_total_in_lei(rates_dir):
    token = _signup("total@example.com")
    _set_currency(token, "RON")

    client.post("/api/expenses", headers=_auth(token), json={"amount": 10, "currency": "EUR"})
    client.post("/api/expenses", headers=_auth(token), json={"amount": 50})

    stats = client.get("/api/me/stats", headers=_auth(token)).json()
    assert stats["total_all_time"] == pytest.approx(52.524 + 50, abs=0.01)


def test_editing_the_amount_reconverts_it(rates_dir):
    token = _signup("edit@example.com")
    _set_currency(token, "RON")

    created = client.post("/api/expenses", headers=_auth(token), json={"amount": 25, "currency": "EUR"}).json()
    updated = client.put(
        f"/api/expenses/{created['id']}", headers=_auth(token), json={"amount": 10, "currency": "USD"}
    ).json()

    assert updated["amount"] == pytest.approx(45.20, abs=0.01)
    assert updated["original_currency"] == "USD"


def test_editing_back_to_the_home_currency_clears_the_conversion(rates_dir):
    token = _signup("clear@example.com")
    _set_currency(token, "RON")

    created = client.post("/api/expenses", headers=_auth(token), json={"amount": 25, "currency": "EUR"}).json()
    updated = client.put(f"/api/expenses/{created['id']}", headers=_auth(token), json={"amount": 40}).json()

    assert updated["amount"] == 40
    assert updated["original_currency"] is None
    assert updated["fx_rate"] is None


def test_an_unknown_currency_is_rejected_rather_than_logged_one_to_one(rates_dir):
    token = _signup("unknown@example.com")
    _set_currency(token, "RON")

    r = client.post("/api/expenses", headers=_auth(token), json={"amount": 25, "currency": "XYZ"})
    assert r.status_code == 400


def test_chat_message_converts_a_currency_it_was_given(rates_dir):
    token = _signup("chat@example.com")
    _set_currency(token, "RON")

    body = client.post("/api/chat/message", headers=_auth(token), json={"text": "25 eur benzina"}).json()
    assert body["parsed"] is True
    assert body["amount"] == pytest.approx(131.31)
    assert body["original_amount"] == 25
    assert body["original_currency"] == "EUR"


def test_a_user_whose_currency_is_eur_converts_the_other_way(rates_dir):
    token = _signup("euro@example.com")
    _set_currency(token, "EUR")

    # Nothing about this is RON-specific: RON is just the snapshot's base.
    body = client.post("/api/expenses", headers=_auth(token), json={"amount": 100, "currency": "RON"}).json()
    assert body["amount"] == pytest.approx(19.04, abs=0.01)
    assert body["original_currency"] == "RON"
