import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app

# Use a fresh in-memory database for tests, separate from dev's expenses.db.
# StaticPool is required for :memory: SQLite so every connection shares the
# same database instead of each getting its own empty one.
TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
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


def test_health_check():
    r = client.get("/")
    assert r.status_code == 200


def test_webhook_logs_expense_and_replies():
    r = client.post(
        "/webhook/whatsapp",
        data={"From": "whatsapp:+40712345678", "Body": "50 groceries"},
    )
    assert r.status_code == 200
    # Sheets isn't configured in tests, so the reply should say so rather than claim success.
    assert "Logged 50.00 (groceries)" in r.text
    assert "sheet wasn't updated" in r.text


def test_webhook_unparseable_message_asks_to_rephrase():
    r = client.post(
        "/webhook/whatsapp",
        data={"From": "whatsapp:+40712345678", "Body": "hey there"},
    )
    assert r.status_code == 200
    assert "Couldn't find an amount" in r.text


def test_summary_reflects_logged_expenses():
    phone = "whatsapp:+40799999999"
    client.post("/webhook/whatsapp", data={"From": phone, "Body": "20 coffee"})
    client.post("/webhook/whatsapp", data={"From": phone, "Body": "30 coffee"})
    client.post("/webhook/whatsapp", data={"From": phone, "Body": "15 taxi"})

    r = client.get(f"/api/users/{phone}/summary")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 65.0
    categories = {c["category"]: c["total"] for c in data["by_category"]}
    assert categories["coffee"] == 50.0
    assert categories["taxi"] == 15.0


def test_unencoded_plus_sign_still_resolves_correctly():
    """
    Regression test: a raw '+' in form data becomes a space per
    x-www-form-urlencoded rules. This confirms lookups still work even if
    a caller sends the number without percent-encoding, or with it.
    """
    client.post(
        "/webhook/whatsapp",
        data={"From": "whatsapp: 40788888888", "Body": "40 fuel"},  # unencoded, arrives as a space
    )
    r = client.get("/api/users/whatsapp:+40788888888/summary")
    assert r.status_code == 200
    assert r.json()["total"] == 40.0


def test_webhook_works_even_when_sheets_not_configured():
    """
    Google Sheets isn't wired up in this test environment. This confirms
    the webhook still logs to the database and replies normally - saying
    the sheet wasn't updated - rather than failing because the sheet
    mirror couldn't be reached.
    """
    r = client.post(
        "/webhook/whatsapp",
        data={"From": "whatsapp:+40766666666", "Body": "18 pharmacy"},
    )
    assert r.status_code == 200
    assert "Logged 18.00 (pharmacy)" in r.text


def test_unknown_number_summary_returns_404():
    r = client.get("/api/users/whatsapp:+10000000000/summary")
    assert r.status_code == 404
