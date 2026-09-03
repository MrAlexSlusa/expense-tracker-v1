import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.parser import parse_expense_message


def test_simple_amount_and_category():
    r = parse_expense_message("50 groceries")
    assert r.amount == 50.0
    assert r.category == "groceries"


def test_decimal_amount():
    r = parse_expense_message("20.5 coffee")
    assert r.amount == 20.5
    assert r.category == "coffee"


def test_natural_phrasing_spent_on():
    r = parse_expense_message("spent 30 on lunch")
    assert r.amount == 30.0
    assert r.category == "lunch"


def test_natural_phrasing_paid_for():
    r = parse_expense_message("paid 15 for taxi")
    assert r.amount == 15.0
    assert r.category == "taxi"


def test_currency_symbol():
    r = parse_expense_message("$12.99 netflix")
    assert r.amount == 12.99
    assert r.category == "netflix"


def test_comma_decimal_european_format():
    r = parse_expense_message("45,50 lei cinema")
    assert r.amount == 45.5
    assert r.category == "cinema"


def test_amount_only_no_category():
    r = parse_expense_message("100")
    assert r.amount == 100.0
    assert r.category is None


def test_multi_word_category():
    r = parse_expense_message("expense 22 fast food dinner")
    assert r.amount == 22.0
    assert r.category == "fast food dinner"


def test_no_amount_returns_none():
    r = parse_expense_message("hey what's up")
    assert r is None


def test_empty_message_returns_none():
    r = parse_expense_message("   ")
    assert r is None


def test_zero_amount_rejected():
    r = parse_expense_message("0 groceries")
    assert r is None
