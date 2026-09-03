import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import sheets

CATEGORIES = [
    "Mancare in oras", "Lounge", "Supermarket", "Vodafone", "Bolt / Uber",
    "Google One", "iCloud", "Spotify", "Parcari", "Tuns", "Altele",
]


class FakeWorksheet:
    """Mimics the slice of gspread's Worksheet API sheets.py relies on."""

    def __init__(self, categories):
        self.amounts = {row: 0.0 for row, _ in enumerate(categories, start=sheets.FIRST_CATEGORY_ROW)}
        self.categories = {row: name for row, name in zip(
            range(sheets.FIRST_CATEGORY_ROW, sheets.FIRST_CATEGORY_ROW + len(categories)), categories
        )}

    def col_values(self, col):
        assert col == sheets.CATEGORY_COLUMN
        last_row = max(self.categories)
        return ["" for _ in range(sheets.FIRST_CATEGORY_ROW - 1)] + [
            self.categories.get(r, "") for r in range(sheets.FIRST_CATEGORY_ROW, last_row + 1)
        ]

    def cell(self, row, col, value_render_option=None):
        assert col == sheets.AMOUNT_COLUMN
        class _Cell:
            def __init__(self, value):
                self.value = value
        return _Cell(self.amounts[row])

    def update_cell(self, row, col, value):
        assert col == sheets.AMOUNT_COLUMN
        self.amounts[row] = value


def test_finds_row_for_exact_category_name():
    ws = FakeWorksheet(CATEGORIES)
    row, name = sheets._find_category_row(ws, "supermarket")
    assert name == "Supermarket"


def test_finds_row_for_close_typo():
    ws = FakeWorksheet(CATEGORIES)
    row, name = sheets._find_category_row(ws, "supermrket")
    assert name == "Supermarket"


def test_unrecognized_word_falls_back_to_altele():
    ws = FakeWorksheet(CATEGORIES)
    row, name = sheets._find_category_row(ws, "auchan")
    assert name == "Altele"


def test_no_category_falls_back_to_altele():
    ws = FakeWorksheet(CATEGORIES)
    row, name = sheets._find_category_row(ws, None)
    assert name == "Altele"


def test_record_expense_adds_to_existing_total(monkeypatch):
    ws = FakeWorksheet(CATEGORIES)
    supermarket_row = next(r for r, name in ws.categories.items() if name == "Supermarket")
    ws.amounts[supermarket_row] = 859.96

    monkeypatch.setattr(sheets, "_get_worksheet", lambda: ws)

    result = sheets.record_expense(category="supermarket", amount=50)
    assert result.success is True
    assert result.category == "Supermarket"
    assert ws.amounts[supermarket_row] == 909.96


def test_record_expense_returns_failure_when_sheet_unavailable(monkeypatch):
    monkeypatch.setattr(sheets, "_get_worksheet", lambda: None)
    result = sheets.record_expense(category="supermarket", amount=50)
    assert result.success is False
    assert result.reason
