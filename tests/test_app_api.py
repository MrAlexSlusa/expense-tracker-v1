import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import io

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from openpyxl import Workbook

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


def _signup(email="alex@example.com", password="hunter2222") -> str:
    r = client.post("/api/auth/signup", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_signup_defaults_goal_split():
    token = _signup("goals@example.com")
    r = client.get("/api/me", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["wants_goal_pct"] == 50.0
    assert body["needs_goal_pct"] == 40.0
    assert body["savings_goal_pct"] == 10.0
    assert body["avatar_url"] is None


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


def test_update_goals_must_sum_to_100():
    token = _signup("goalcheck@example.com")
    r = client.put("/api/me/goals", headers=_auth(token), json={"wants_pct": 60, "needs_pct": 30, "savings_pct": 20})
    assert r.status_code == 400

    r = client.put("/api/me/goals", headers=_auth(token), json={"wants_pct": 60, "needs_pct": 30, "savings_pct": 10})
    assert r.status_code == 200
    assert r.json()["wants_goal_pct"] == 60


def test_stats_reflect_logged_expenses():
    token = _signup("stats@example.com")
    client.post("/api/expenses", headers=_auth(token), json={"amount": 25.0, "note": "lunch"})
    client.post("/api/expenses", headers=_auth(token), json={"amount": 15.0, "note": "coffee"})

    r = client.get("/api/me/stats", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["total_all_time"] == 40.0
    assert body["current_streak_days"] >= 1


def test_income_crud_scoped_to_period():
    token = _signup("income@example.com")
    r = client.post("/api/income", headers=_auth(token), json={"name": "Salary", "amount": 3000, "period": "2026-01"})
    assert r.status_code == 200
    income_id = r.json()["id"]

    r = client.get("/api/income?period=2026-01", headers=_auth(token))
    assert len(r.json()) == 1
    r = client.get("/api/income?period=2026-02", headers=_auth(token))
    assert len(r.json()) == 0

    r = client.put(f"/api/income/{income_id}", headers=_auth(token), json={"amount": 3200})
    assert r.json()["amount"] == 3200

    r = client.delete(f"/api/income/{income_id}", headers=_auth(token))
    assert r.status_code == 200


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
    assert body["income_rows"] == 2

    r = client.get("/api/budget?period=2026-01", headers=_auth(token))
    names = {c["name"]: c for c in r.json()}
    assert names["Mancare in oras"]["total"] == 996.97
    assert names["Mancare in oras"]["tag"] == "Wants"

    r = client.get("/api/income?period=2026-01", headers=_auth(token))
    assert {i["name"] for i in r.json()} == {"Cash", "ING"}

    r = client.get("/api/me", headers=_auth(token))
    assert r.json()["wants_goal_pct"] == 60.0


def test_budget_goals_actual_pct_matches_spreadsheet_math():
    # Real Jan 2026 sheet: Wants spend 2.282,43 / TOTAL INCOME 3.365,00 = 67,83%,
    # the exact ACTUAL row in that sheet - actual % is a share of income, not
    # of total spend.
    token = _signup("goalsmath@example.com")
    client.post("/api/income", headers=_auth(token), json={"name": "Cash", "amount": 3365.00, "period": "2026-01"})
    client.post("/api/budget/categories", headers=_auth(token), json={"name": "Dining", "tag": "Wants"})
    categories = {c["name"]: c["id"] for c in client.get("/api/budget?period=2026-01", headers=_auth(token)).json()}
    client.post(
        "/api/expenses",
        headers=_auth(token),
        json={"amount": 2282.43, "category_id": categories["Dining"], "date": "2026-01-15"},
    )

    r = client.get("/api/budget/goals?period=2026-01", headers=_auth(token))
    wants = next(g for g in r.json() if g["tag"] == "Wants")
    assert wants["actual_pct"] == 67.83


def test_reimporting_same_period_replaces_not_duplicates():
    token = _signup("reimport@example.com")
    files = {"file": ("2026 Jan Budget.xlsx", _xlsx_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    client.post("/api/import/spreadsheet", headers=_auth(token), files=files)
    client.post("/api/import/spreadsheet", headers=_auth(token), files=files)

    r = client.get("/api/budget?period=2026-01", headers=_auth(token))
    names = {c["name"]: c for c in r.json()}
    assert names["Mancare in oras"]["total"] == 996.97  # not doubled

    r = client.get("/api/income?period=2026-01", headers=_auth(token))
    assert len(r.json()) == 2  # not doubled
