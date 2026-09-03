import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app

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


def _signup(email, password="hunter2222") -> str:
    r = client.post("/api/auth/signup", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_account_crud_round_trip():
    token = _signup("accounts@example.com")

    created = client.post(
        "/api/accounts",
        headers=_auth(token),
        json={"name": "Emirates NBD", "kind": "Current", "last4": "1042", "balance": 12480, "icon": "\U0001F3E6"},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["label"] == "Emirates NBD \u00b71042"
    assert body["balance"] == 12480.0

    listed = client.get("/api/accounts", headers=_auth(token))
    assert [a["name"] for a in listed.json()] == ["Emirates NBD"]

    updated = client.put(
        f"/api/accounts/{body['id']}", headers=_auth(token), json={"balance": 12000, "clear_last4": True}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["label"] == "Emirates NBD"  # no last4 left to append
    assert updated.json()["balance"] == 12000.0

    assert client.delete(f"/api/accounts/{body['id']}", headers=_auth(token)).status_code == 200
    assert client.get("/api/accounts", headers=_auth(token)).json() == []


def test_expense_carries_its_account_and_survives_the_account_being_deleted():
    token = _signup("txaccount@example.com")
    account_id = client.post(
        "/api/accounts", headers=_auth(token), json={"name": "Wio", "kind": "Debit", "last4": "8871"}
    ).json()["id"]

    expense = client.post(
        "/api/expenses", headers=_auth(token), json={"amount": 86, "account_id": account_id, "note": "Dinner"}
    )
    assert expense.status_code == 200, expense.text
    assert expense.json()["account_name"] == "Wio \u00b78871"

    client.delete(f"/api/accounts/{account_id}", headers=_auth(token))
    remaining = client.get("/api/expenses", headers=_auth(token)).json()
    assert len(remaining) == 1
    assert remaining[0]["amount"] == 86
    assert remaining[0]["account_id"] is None


def test_account_of_another_user_is_not_reachable():
    mine = _signup("owner@example.com")
    theirs = _signup("intruder@example.com")
    account_id = client.post("/api/accounts", headers=_auth(mine), json={"name": "Cash"}).json()["id"]

    assert client.put(f"/api/accounts/{account_id}", headers=_auth(theirs), json={"name": "Nope"}).status_code == 404
    assert client.delete(f"/api/accounts/{account_id}", headers=_auth(theirs)).status_code == 404
    assert client.post(
        "/api/expenses", headers=_auth(theirs), json={"amount": 10, "account_id": account_id}
    ).status_code == 404


def test_linked_accounts_shows_up_in_stats():
    token = _signup("stataccounts@example.com")
    assert client.get("/api/me/stats", headers=_auth(token)).json()["linked_accounts"] == 0
    client.post("/api/accounts", headers=_auth(token), json={"name": "Cash", "kind": "Wallet"})
    assert client.get("/api/me/stats", headers=_auth(token)).json()["linked_accounts"] == 1


# --- Date ranges: what the app's period sheet asks for beyond one month ---


def test_expenses_and_budget_accept_an_explicit_date_range():
    token = _signup("ranges@example.com")
    category_id = client.post(
        "/api/budget/categories", headers=_auth(token), json={"name": "Groceries"}
    ).json()["id"]

    for date, amount in (("2026-01-15", 100), ("2026-02-10", 250), ("2026-03-05", 40)):
        client.post(
            "/api/expenses",
            headers=_auth(token),
            json={"amount": amount, "category_id": category_id, "date": date},
        )

    spanning = client.get(
        "/api/expenses?start=2026-01-01&end=2026-02-28", headers=_auth(token)
    )
    assert spanning.status_code == 200, spanning.text
    assert sorted(e["amount"] for e in spanning.json()) == [100.0, 250.0]

    budget = client.get("/api/budget?start=2026-01-01&end=2026-02-28", headers=_auth(token))
    groceries = next(c for c in budget.json() if c["name"] == "Groceries")
    assert groceries["total"] == 350.0

    # The last day of the range counts, whatever time of day the row carries.
    inclusive = client.get("/api/expenses?start=2026-03-05&end=2026-03-05", headers=_auth(token))
    assert [e["amount"] for e in inclusive.json()] == [40.0]


def test_half_a_range_and_a_backwards_range_are_rejected():
    token = _signup("badranges@example.com")
    assert client.get("/api/expenses?start=2026-01-01", headers=_auth(token)).status_code == 400
    assert client.get(
        "/api/expenses?start=2026-03-01&end=2026-01-01", headers=_auth(token)
    ).status_code == 400
    assert client.get(
        "/api/expenses?start=March&end=April", headers=_auth(token)
    ).status_code == 400


def test_goal_actuals_use_income_from_every_month_the_range_touches():
    token = _signup("rangegoals@example.com")
    category_id = client.post(
        "/api/budget/categories", headers=_auth(token), json={"name": "Rent", "tag": "Needs"}
    ).json()["id"]
    client.post(
        "/api/expenses",
        headers=_auth(token),
        json={"amount": 900, "category_id": category_id, "date": "2026-02-01"},
    )
    client.post("/api/income", headers=_auth(token), json={"name": "Salary", "amount": 1000, "period": "2026-01"})
    client.post("/api/income", headers=_auth(token), json={"name": "Salary", "amount": 2000, "period": "2026-02"})

    goals = client.get("/api/budget/goals?start=2026-01-01&end=2026-02-28", headers=_auth(token)).json()
    needs = next(g for g in goals if g["tag"] == "Needs")
    assert needs["actual_amount"] == 900.0
    assert needs["actual_pct"] == 30.0  # 900 of the 3000 earned across both months
