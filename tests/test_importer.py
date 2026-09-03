import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import io
import csv

from openpyxl import Workbook

from app.importer import parse_workbook, guess_period_from_filename


def _build_january_workbook() -> bytes:
    """
    Mirrors the real "2026 Jan Budget" sheet: two parallel tables (income in
    A/B, spending+tag in C/D/E), a row where the income side has run out
    (only C-G populated), a row with a blank spending amount (Parcari), a
    stray noise row, and a trailing GOALS/ACTUAL block.
    """
    wb = Workbook()
    ws = wb.active
    rows = [
        ["\U0001F436 January Budget Tracker"],
        ["INCOME", "SPENDINGS", None, None, "Ultima: 31"],
        ["Cash", "1.500,00 lei", "Mancare in oras", "996,97 lei", "Wants"],
        ["ING", "400,00 lei", "Lounge", "197,00 lei", "Wants"],
        ["Revolut Ramas", "200,00 lei", "Supermarket", "586,09 lei", "Needs"],
        ["Mama", "200,00 lei", "Vodafone", "69,10 lei", "Needs"],
        ["Edenred", "1.065,00 lei", "Bolt", "36,10 lei", "Wants"],
        [None, None, "Google One", "13,99 lei", "Needs", "TOTAL INCOME", "3.365,00 lei"],
        [None, None, "iCloud", "4,99 lei", "Needs"],
        [None, None, "Spotify", "26,00 lei", "Needs"],
        [None, None, "Parcari", "Needs", None, "TOTAL EXPENSES", "3.056,40 lei"],
        [None, None, "Tuns", "50,00 lei", "Needs"],
        [None, None, "Altele", "1.013,36 lei", "Wants", "Ramas", "308,60 lei"],
        [None, None, "Tigari", "39,00 lei", "Wants"],
        ["ASDFGHJ"],
        ["GOALS", "WANTS", "50,00%", "1.682,50 lei"],
        ["NEEDS", "40,00%", "1.346,00 lei"],
        ["SAVINGS", "10,00%", "336,50 lei"],
        ["ACTUAL", "WANTS", "67,83%", "2.282,43 lei"],
        ["NEEDS", "23,00%", "773,97 lei"],
        ["SAVINGS", "0,00%", "0,00 lei"],
    ]
    for row in rows:
        ws.append(row)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parses_income_rows():
    result = parse_workbook(_build_january_workbook(), "2026 Jan Budget.xlsx")
    income_by_name = {r.name: r.amount for r in result.income}
    assert income_by_name["Cash"] == 1500.0
    assert income_by_name["ING"] == 400.0
    assert income_by_name["Edenred"] == 1065.0
    assert len(result.income) == 5


def test_parses_spending_categories_with_tags():
    result = parse_workbook(_build_january_workbook(), "2026 Jan Budget.xlsx")
    by_name = {r.name: r for r in result.categories}
    assert by_name["Mancare in oras"].amount == 996.97
    assert by_name["Mancare in oras"].tag == "Wants"
    assert by_name["Supermarket"].tag == "Needs"
    assert by_name["Altele"].amount == 1013.36
    # "Parcari" has no amount cell in the real sheet - skipped, not crashed on
    assert "Parcari" not in by_name


def test_warns_on_missing_amount():
    result = parse_workbook(_build_january_workbook(), "2026 Jan Budget.xlsx")
    assert any("Parcari" in w for w in result.warnings)


def test_ignores_noise_row():
    result = parse_workbook(_build_january_workbook(), "2026 Jan Budget.xlsx")
    names = [r.name for r in result.income] + [r.name for r in result.categories]
    assert "ASDFGHJ" not in names


def test_parses_goals_block():
    result = parse_workbook(_build_january_workbook(), "2026 Jan Budget.xlsx")
    assert result.goals["Wants"].target_pct == 50.0
    assert result.goals["Needs"].target_pct == 40.0
    assert result.goals["Savings"].target_pct == 10.0
    assert result.goals["Wants"].actual_pct == 67.83


def test_csv_variant_parses_the_same_shape():
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Cash", "1.500,00 lei", "Mancare in oras", "996,97 lei", "Wants"])
    writer.writerow(["ING", "400,00 lei", "Supermarket", "586,09 lei", "Needs"])
    content = buf.getvalue().encode("utf-8")

    result = parse_workbook(content, "budget.csv")
    assert len(result.income) == 2
    assert len(result.categories) == 2
    assert result.categories[0].tag == "Wants"


def test_guess_period_from_filename():
    assert guess_period_from_filename("2026 Aug Budget.xlsx") == "2026-08"
    assert guess_period_from_filename("2026 Jan Budget") == "2026-01"
    assert guess_period_from_filename("random.xlsx") is None


def test_unsupported_extension_raises():
    import pytest

    with pytest.raises(ValueError):
        parse_workbook(b"whatever", "budget.pdf")
