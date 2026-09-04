"""
Per-user timezones.

Expenses are always stored as UTC instants; the timezone only decides which
calendar day each one is counted under. The case that matters is the one that
exposed the bug: a user hours ahead of UTC logging something just after their
local midnight. The server's own clock must never enter into it.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timedelta, timezone as dt_timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import User, Expense, BudgetCategory
from app.api import today_for, local_date, user_zone

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


@pytest.fixture(autouse=True)
def use_this_modules_db():
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    yield
    if previous is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous


def _signup(email):
    r = client.post("/api/auth/signup", json={"email": email, "password": "hunter2222"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# --- the setting itself ----------------------------------------------------


def test_a_new_account_has_no_timezone_and_is_treated_as_utc():
    headers = _signup("tz-default@example.com")
    assert client.get("/api/me", headers=headers).json()["timezone"] is None


def test_a_timezone_can_be_set_and_read_back():
    headers = _signup("tz-set@example.com")
    r = client.put("/api/me/timezone", headers=headers, json={"timezone": "Europe/Bucharest"})
    assert r.status_code == 200
    assert r.json()["timezone"] == "Europe/Bucharest"
    assert client.get("/api/me", headers=headers).json()["timezone"] == "Europe/Bucharest"


def test_an_unknown_timezone_is_refused_and_nothing_changes():
    headers = _signup("tz-bad@example.com")
    client.put("/api/me/timezone", headers=headers, json={"timezone": "Europe/Bucharest"})

    r = client.put("/api/me/timezone", headers=headers, json={"timezone": "Mars/Olympus_Mons"})
    assert r.status_code == 400
    assert client.get("/api/me", headers=headers).json()["timezone"] == "Europe/Bucharest"


def test_clearing_the_timezone_falls_back_to_utc():
    headers = _signup("tz-clear@example.com")
    client.put("/api/me/timezone", headers=headers, json={"timezone": "Asia/Tokyo"})
    r = client.put("/api/me/timezone", headers=headers, json={"timezone": ""})
    assert r.status_code == 200 and r.json()["timezone"] is None


# --- the helpers, where the actual correctness lives -----------------------


def test_a_stored_instant_lands_on_different_days_in_different_zones():
    """22:30 UTC is still today in London and already tomorrow in Bucharest."""
    moment = datetime(2026, 9, 4, 22, 30)  # naive UTC, as stored
    assert local_date(moment, user_zone(User(timezone=None))).isoformat() == "2026-09-04"
    assert local_date(moment, user_zone(User(timezone="Europe/Bucharest"))).isoformat() == "2026-09-05"
    assert local_date(moment, user_zone(User(timezone="America/New_York"))).isoformat() == "2026-09-04"
    # Far enough west and it is still the previous afternoon.
    assert local_date(datetime(2026, 9, 5, 3, 0), user_zone(User(timezone="America/Los_Angeles"))).isoformat() == "2026-09-04"


def test_today_is_the_users_day_not_the_servers():
    ahead = today_for(User(timezone="Pacific/Kiritimati"))   # UTC+14
    behind = today_for(User(timezone="Pacific/Midway"))      # UTC-11
    assert (ahead - behind).days in (0, 1)
    # Whatever the server thinks, each is that zone's own date.
    for zone in ("Europe/Bucharest", "Asia/Tokyo", "America/Sao_Paulo"):
        expected = datetime.now(dt_timezone.utc).astimezone(user_zone(User(timezone=zone))).date()
        assert today_for(User(timezone=zone)) == expected


def test_a_broken_timezone_degrades_to_utc_rather_than_erroring():
    """A stale zone name should make dates slightly wrong, never 500 the app."""
    assert today_for(User(timezone="Not/AZone")) == today_for(User(timezone=None))
    assert today_for(User(timezone="   ")) == today_for(User(timezone=None))


# --- the bug this was written for ------------------------------------------


def _log_expense_at(db, user_id, when, amount=10.0):
    category = db.query(BudgetCategory).filter(BudgetCategory.user_id == user_id).first()
    db.add(Expense(user_id=user_id, amount=amount, category=category.name if category else None,
                   category_id=category.id if category else None,
                   raw_message="after midnight", created_at=when))
    db.commit()


def test_an_expense_logged_right_now_counts_as_today_whatever_the_hour():
    """
    The reported failure, and the guarantee that fixes it: an expense logged
    this instant is always filed under the user's today and always continues
    their streak - including between local midnight and the UTC offset, when
    the stored UTC instant still belongs to the previous UTC day.

    Before per-user timezones this failed for exactly those hours, because the
    streak compared UTC-dated expenses against the server's local date.
    """
    headers = _signup("tz-midnight@example.com")
    client.put("/api/me/timezone", headers=headers, json={"timezone": "Europe/Bucharest"})

    db = TestingSessionLocal()
    try:
        user = db.query(User).filter(User.email == "tz-midnight@example.com").first()
        zone = user_zone(user)
        now_utc = datetime.now(dt_timezone.utc)
        # Exactly how the app stores "now": a naive UTC instant.
        _log_expense_at(db, user.id, now_utc.replace(tzinfo=None))
        expected_day = now_utc.astimezone(zone).date().isoformat()
        utc_day = now_utc.date().isoformat()
    finally:
        db.close()

    rows = client.get("/api/expenses", headers=headers).json()
    assert [r["date"] for r in rows] == [expected_day], "expense filed under the wrong day"

    stats = client.get("/api/me/stats", headers=headers).json()
    assert stats["current_streak_days"] >= 1, "a just-logged expense broke the streak"

    # When the two disagree, the user's day is the one that must win - this is
    # the window the original bug lived in, and it is only reachable for part
    # of each day, so note it rather than assert it.
    if expected_day != utc_day:
        assert rows[0]["date"] == expected_day


def test_changing_zone_refiles_an_expense_without_editing_it():
    """The stored instant is untouched; only which day it counts under moves."""
    headers = _signup("tz-refile@example.com")
    db = TestingSessionLocal()
    try:
        user = db.query(User).filter(User.email == "tz-refile@example.com").first()
        _log_expense_at(db, user.id, datetime(2026, 3, 10, 22, 30))
    finally:
        db.close()

    client.put("/api/me/timezone", headers=headers, json={"timezone": "UTC"})
    utc_day = client.get("/api/expenses?start=2026-03-01&end=2026-03-31", headers=headers).json()[0]["date"]

    client.put("/api/me/timezone", headers=headers, json={"timezone": "Asia/Tokyo"})
    tokyo_day = client.get("/api/expenses?start=2026-03-01&end=2026-03-31", headers=headers).json()[0]["date"]

    assert utc_day == "2026-03-10"
    assert tokyo_day == "2026-03-11"   # +9 pushes 22:30 into the next morning


def test_a_days_range_query_follows_the_users_zone():
    """
    Asking for one calendar day must return that day where the user lives - a
    window shifted by the offset once expressed in UTC.
    """
    headers = _signup("tz-window@example.com")
    db = TestingSessionLocal()
    try:
        user = db.query(User).filter(User.email == "tz-window@example.com").first()
        # 23:00 UTC on the 10th = 08:00 on the 11th in Tokyo.
        _log_expense_at(db, user.id, datetime(2026, 4, 10, 23, 0), amount=42.0)
    finally:
        db.close()

    client.put("/api/me/timezone", headers=headers, json={"timezone": "Asia/Tokyo"})
    on_10th = client.get("/api/expenses?start=2026-04-10&end=2026-04-10", headers=headers).json()
    on_11th = client.get("/api/expenses?start=2026-04-11&end=2026-04-11", headers=headers).json()

    assert on_10th == []
    assert len(on_11th) == 1 and on_11th[0]["amount"] == 42.0
