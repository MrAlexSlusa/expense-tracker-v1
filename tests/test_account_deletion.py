"""
DELETE /api/me - the endpoint behind the privacy policy's promise that asking
removes everything. The cases that matter: it really is everything, one user's
delete doesn't touch another's, and an unattended session can't trigger it
without the password.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import User, Expense, BudgetCategory, IncomeSource, Account, OtpCode
from app import oauth

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


client = TestClient(app)


# Every test module here overrides get_db at import time, so this file claims
# the override for its own tests and hands it back afterwards - it reads the
# database directly to prove rows are gone.
@pytest.fixture(autouse=True)
def use_this_modules_db():
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    yield
    if previous is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous


PASSWORD = "hunter2222"


def _signup(email):
    r = client.post("/api/auth/signup", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _fill_account(headers):
    """Give the account one of everything, so deletion has something to miss."""
    cats = client.get("/api/budget", headers=headers).json()
    category_id = cats[0]["id"]
    account_id = client.post(
        "/api/accounts", headers=headers, json={"name": "Cash", "balance": 10}
    ).json()["id"]
    client.post(
        "/api/expenses", headers=headers,
        json={"amount": 12.5, "category_id": category_id, "account_id": account_id, "note": "lunch"},
    )
    client.post("/api/income", headers=headers, json={"name": "Salary", "amount": 100})
    return category_id, account_id


def _counts(email):
    db = TestingSessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            return None
        return {
            "expenses": db.query(Expense).filter(Expense.user_id == user.id).count(),
            "categories": db.query(BudgetCategory).filter(BudgetCategory.user_id == user.id).count(),
            "accounts": db.query(Account).filter(Account.user_id == user.id).count(),
            "income": db.query(IncomeSource).filter(IncomeSource.user_id == user.id).count(),
            "otp": db.query(OtpCode).filter(OtpCode.user_id == user.id).count(),
        }
    finally:
        db.close()


def test_deleting_an_account_removes_the_user_and_everything_it_owned():
    email = "goodbye@example.com"
    headers = _signup(email)
    _fill_account(headers)
    assert _counts(email)["expenses"] == 1

    r = client.request("DELETE", "/api/me", headers=headers, json={"password": PASSWORD})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] is True
    assert body["expenses"] == 1 and body["income"] == 1 and body["accounts"] == 1

    assert _counts(email) is None  # the user row itself is gone

    db = TestingSessionLocal()
    try:
        # Nothing orphaned: no row anywhere still points at the dead user.
        assert db.query(User).filter(User.email == email).count() == 0
        for model in (Expense, BudgetCategory, Account, IncomeSource, OtpCode):
            assert db.query(model).count() == db.query(model).filter(model.user_id.isnot(None)).count()
    finally:
        db.close()


def test_the_token_stops_working_afterwards():
    headers = _signup("gone@example.com")
    client.request("DELETE", "/api/me", headers=headers, json={"password": PASSWORD})
    assert client.get("/api/me", headers=headers).status_code == 401


def test_the_email_can_be_used_to_sign_up_again():
    email = "reuse@example.com"
    headers = _signup(email)
    client.request("DELETE", "/api/me", headers=headers, json={"password": PASSWORD})
    assert client.post("/api/auth/signup", json={"email": email, "password": PASSWORD}).status_code == 200


def test_a_password_account_cannot_be_deleted_without_the_password():
    email = "protected@example.com"
    headers = _signup(email)

    assert client.request("DELETE", "/api/me", headers=headers).status_code == 400
    assert client.request("DELETE", "/api/me", headers=headers, json={}).status_code == 400
    wrong = client.request("DELETE", "/api/me", headers=headers, json={"password": "wrong-password"})
    assert wrong.status_code == 401
    # The frontend maps this exact string to a translated message and, crucially,
    # treats it as a wrong password rather than an expired session - so the
    # wording is part of the contract, not just prose.
    assert wrong.json()["detail"] == "Incorrect password"

    assert _counts(email) is not None  # still there after all three refusals


def test_a_social_only_account_deletes_without_a_password(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setattr(oauth, "exchange_code", lambda *a, **kw: {"access_token": "t"})
    monkeypatch.setattr(oauth, "fetch_identity", lambda *a, **kw: ("social@example.com", "sub-9", None))
    front = "http://localhost:5500/index.html"
    r = client.get(
        "/api/auth/oauth/google/callback",
        params={"code": "abc", "state": oauth.encode_state("google", front)},
        follow_redirects=False,
    )
    headers = {"Authorization": f"Bearer {r.headers['location'].split('#token=')[1]}"}

    assert client.request("DELETE", "/api/me", headers=headers).status_code == 200
    assert _counts("social@example.com") is None


def test_deleting_one_account_leaves_another_alone():
    keeper = "keeper@example.com"
    keeper_headers = _signup(keeper)
    _fill_account(keeper_headers)

    doomed_headers = _signup("doomed@example.com")
    _fill_account(doomed_headers)
    client.request("DELETE", "/api/me", headers=doomed_headers, json={"password": PASSWORD})

    assert _counts("doomed@example.com") is None
    survivor = _counts(keeper)
    assert survivor["expenses"] == 1 and survivor["accounts"] == 1 and survivor["income"] == 1
    assert client.get("/api/me", headers=keeper_headers).status_code == 200
