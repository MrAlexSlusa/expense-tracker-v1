import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from openpyxl import Workbook

from app.database import Base, get_db
from app.main import app
from app.starter import starter_categories
from app.models import User, BudgetCategory

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


@pytest.fixture(autouse=True)
def use_this_modules_db():
    """
    Points the app at this module's database for the duration of each test.

    Every test module installs its own get_db override at import time, so the
    last one imported wins for the whole session. That is harmless while a
    module only talks over HTTP, but some tests here also hold a Session of
    their own and assert across both - so the override is (re)installed per
    test rather than once at import.
    """
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    yield
    if previous is not None:
        app.dependency_overrides[get_db] = previous
client = TestClient(app)


def _signup(email="alex@example.com", password="hunter2222") -> str:
    r = client.post("/api/auth/signup", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_update_profile_display_name_and_avatar():
    token = _signup("profile@example.com")
    tiny_png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    r = client.put("/api/me/profile", headers=_auth(token), json={"display_name": "Alex", "avatar_url": tiny_png})
    assert r.status_code == 200, r.text
    assert r.json()["display_name"] == "Alex"
    assert r.json()["avatar_url"] == tiny_png


def test_update_profile_rejects_non_image_avatar():
    token = _signup("badavatar@example.com")
    r = client.put("/api/me/profile", headers=_auth(token), json={"avatar_url": "data:text/plain;base64,aGk="})
    assert r.status_code == 400


def test_stats_reflect_logged_expenses():
    token = _signup("stats@example.com")
    client.post("/api/expenses", headers=_auth(token), json={"amount": 25.0, "note": "lunch"})
    client.post("/api/expenses", headers=_auth(token), json={"amount": 15.0, "note": "coffee"})

    r = client.get("/api/me/stats", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["total_all_time"] == 40.0


def test_category_tag_round_trips():
    token = _signup("tags@example.com")
    r = client.post("/api/budget/categories", headers=_auth(token), json={"name": "Rent", "tag": "Needs"})
    assert r.json()["tag"] == "Needs"
    category_id = r.json()["id"]

    r = client.put(f"/api/budget/categories/{category_id}", headers=_auth(token), json={"tag": "Wants"})
    assert r.json()["tag"] == "Wants"


def _xlsx_bytes():
    wb = Workbook()
    ws = wb.active
    ws.append(["Cash", "1.500,00 lei", "Mancare in oras", "996,97 lei", "Wants"])
    ws.append(["ING", "400,00 lei", "Supermarket", "586,09 lei", "Needs"])
    ws.append(["GOALS", "WANTS", "60,00%", "1.140,00 lei"])
    ws.append(["NEEDS", "30,00%", "570,00 lei"])
    ws.append(["SAVINGS", "10,00%", "190,00 lei"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_import_spreadsheet_populates_everything():
    token = _signup("import@example.com")
    files = {"file": ("2026 Jan Budget.xlsx", _xlsx_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r = client.post("/api/import/spreadsheet", headers=_auth(token), files=files)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["period"] == "2026-01"
    assert body["categories_created"] == 2

    r = client.get("/api/budget?period=2026-01", headers=_auth(token))
    names = {c["name"]: c for c in r.json()}
    assert names["Mancare in oras"]["total"] == 996.97
    assert names["Mancare in oras"]["tag"] == "Wants"

    # The sheet's income column and GOALS block are stepped over rather than
    # imported, and stepping over them must not disturb the spending rows: what
    # the file adds on top of the starter set is exactly its two spending rows.
    starter = {name for name, _ in starter_categories("en")}
    assert set(names) - starter == {"Mancare in oras", "Supermarket"}


def test_reimporting_same_period_replaces_not_duplicates():
    token = _signup("reimport@example.com")
    files = {"file": ("2026 Jan Budget.xlsx", _xlsx_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    client.post("/api/import/spreadsheet", headers=_auth(token), files=files)
    client.post("/api/import/spreadsheet", headers=_auth(token), files=files)

    r = client.get("/api/budget?period=2026-01", headers=_auth(token))
    names = {c["name"]: c for c in r.json()}
    assert names["Mancare in oras"]["total"] == 996.97  # not doubled


def test_recategorising_moves_the_auto_label_but_keeps_a_real_note():
    """
    An app-logged expense has no note of its own - it is labelled with its
    category's name, and that label is what the transaction row shows. Moving
    the expense to another category has to move the label too, or the row goes
    on announcing the category it no longer belongs to. A note the user wrote
    is theirs and stays put.
    """
    token = _signup("recat@example.com")
    cats = client.post("/api/budget/categories", headers=_auth(token), json={"name": "Groceries"}).json()
    other = client.post("/api/budget/categories", headers=_auth(token), json={"name": "Transport"}).json()

    auto = client.post("/api/expenses", headers=_auth(token),
                       json={"amount": 30.0, "category_id": cats["id"]}).json()
    assert auto["note"] == "Groceries"

    moved = client.put(f"/api/expenses/{auto['id']}", headers=_auth(token),
                       json={"category_id": other["id"]}).json()
    assert moved["category_name"] == "Transport"
    assert moved["note"] == "Transport"

    written = client.post("/api/expenses", headers=_auth(token),
                          json={"amount": 12.0, "category_id": cats["id"], "note": "birthday cake"}).json()
    kept = client.put(f"/api/expenses/{written['id']}", headers=_auth(token),
                      json={"category_id": other["id"]}).json()
    assert kept["category_name"] == "Transport"
    assert kept["note"] == "birthday cake"

    # A label that already drifted - it names a category, just not this row's
    # current one - is still an auto label, and gets put right on the next move.
    drifted = client.post("/api/expenses", headers=_auth(token),
                          json={"amount": 9.0, "category_id": cats["id"], "note": "Transport"}).json()
    repaired = client.put(f"/api/expenses/{drifted['id']}", headers=_auth(token),
                          json={"category_id": other["id"]}).json()
    assert repaired["note"] == "Transport"  # moved to Transport, and now says so
    back = client.put(f"/api/expenses/{drifted['id']}", headers=_auth(token),
                      json={"category_id": cats["id"]}).json()
    assert back["note"] == "Groceries"


# --- One address, one account -------------------------------------------
# Signup and login used to compare the address exactly while social sign-in
# compared it case-insensitively, so Alex@example.com and alex@example.com
# could become two accounts with two separate budgets.


def test_an_address_is_the_same_account_whatever_its_case():
    first = client.post("/api/auth/signup", json={"email": "Case@Example.com", "password": "hunter2222"})
    assert first.status_code == 200

    again = client.post("/api/auth/signup", json={"email": "case@example.com", "password": "different999"})
    assert again.status_code == 400
    assert "already exists" in again.json()["detail"]


def test_login_and_reset_accept_the_address_in_any_case():
    client.post("/api/auth/signup", json={"email": "mixed@example.com", "password": "hunter2222"})

    # The capitals a phone keyboard adds on its own must not lock anyone out.
    for typed in ("mixed@example.com", "Mixed@Example.com", "MIXED@EXAMPLE.COM"):
        login = client.post("/api/auth/login", json={"email": typed, "password": "hunter2222"})
        assert login.status_code == 200, typed
        assert login.json()["access_token"]

    asked = client.post("/api/auth/forgot-password", json={"email": "MIXED@example.com"})
    assert asked.status_code == 200


def test_the_stored_address_is_canonical():
    token = _signup("Canonical@Example.COM")
    me = client.get("/api/me", headers=_auth(token)).json()
    assert me["email"] == "canonical@example.com"


# --- Signing up lands you in the app ------------------------------------
# This used to be a four-question quiz about how you spend your weekends,
# answered before you had seen the app, to pick categories you can change in
# two taps. New accounts now start with a usable set straight away.


def test_signing_up_gives_a_usable_set_of_categories():
    token = _signup("starter@example.com")
    names = [c["name"] for c in client.get("/api/budget", headers=_auth(token)).json()]
    assert names == [name for name, _ in starter_categories("en")]
    assert "Other" in names  # the importer's catch-all has to exist
    assert all(c["icon"] for c in client.get("/api/budget", headers=_auth(token)).json())


def test_the_starter_set_follows_the_signup_language():
    r = client.post("/api/auth/signup", json={"email": "ro@example.com", "password": "hunter2222", "lang": "ro"})
    token = r.json()["access_token"]
    names = {c["name"] for c in client.get("/api/budget", headers=_auth(token)).json()}
    assert "Alimente" in names and "Altele" in names
    assert "Groceries" not in names


def test_an_unknown_language_still_signs_up():
    r = client.post("/api/auth/signup", json={"email": "xx@example.com", "password": "hunter2222", "lang": "xx"})
    assert r.status_code == 200
    names = {c["name"] for c in client.get("/api/budget", headers=_auth(r.json()["access_token"])).json()}
    assert "Other" in names


def test_the_quiz_is_gone():
    assert client.get("/api/quiz").status_code == 404
    token = _signup("noquiz@example.com")
    assert client.post("/api/onboarding/complete", headers=_auth(token),
                       json={"answers": {}, "lang": "en"}).status_code == 404


def test_an_account_left_half_set_up_is_topped_up_on_its_next_visit():
    """
    Accounts created before the quiz was dropped can be sitting on the single
    fallback category it gave them at signup, with no quiz left to finish.
    """
    token = _signup("halfway@example.com")
    db = TestingSessionLocal()
    try:
        user = db.query(User).filter(User.email == "halfway@example.com").first()
        db.query(BudgetCategory).filter(
            BudgetCategory.user_id == user.id, BudgetCategory.name != "Other"
        ).delete(synchronize_session=False)
        user.onboarded = False
        db.commit()
    finally:
        db.close()

    assert len(client.get("/api/budget", headers=_auth(token)).json()) == 1

    client.get("/api/me?lang=ro", headers=_auth(token))

    names = {c["name"] for c in client.get("/api/budget", headers=_auth(token)).json()}
    assert "Alimente" in names
    assert len([n for n in names if n in ("Other", "Altele")]) == 1  # no duplicate catch-all
