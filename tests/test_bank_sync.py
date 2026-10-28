"""
Tests for the bank import: merchant normalisation, the category decision,
and the sync loop that turns transactions into expenses.

The aggregator itself is never called. Every test feeds app.gocardless's
three read functions from a fake, because what is worth testing here is the
filing decision, not httpx - and a test that needs a live PSD2 consent is a
test nobody runs.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import bank_sync, bnr, gocardless
from app.categorizer import normalize_merchant, suggest_category
from app.database import Base, get_db
from app.main import app
from app.models import BankAccount, BankConnection, BankTransaction, Expense, MerchantRule

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
    response = client.post("/api/auth/signup", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth(token):
    return {"Authorization": "Bearer " + token}


def _category(token, name, icon="\U0001F4B0"):
    response = client.post("/api/budget/categories", headers=_auth(token), json={"name": name, "icon": icon})
    assert response.status_code == 200, response.text
    return response.json()


def _user_id(token) -> int:
    return client.get("/api/me", headers=_auth(token)).json()["id"]


def _tx(tx_id, amount, merchant, *, date="2026-10-20", currency="RON", mcc=None):
    """A booked transaction shaped the way GoCardless returns Revolut's."""
    payload = {
        "transactionId": tx_id,
        "bookingDate": date,
        "transactionAmount": {"amount": str(amount), "currency": currency},
        "remittanceInformationUnstructured": merchant,
    }
    if mcc:
        payload["merchantCategoryCode"] = mcc
    return payload


def _link(db, token):
    """A linked Revolut connection with one RON account, ready to sync."""
    # Accounts default to USD, and every amount in these tests is quoted in
    # RON - without this the whole suite would be asserting on converted
    # numbers instead of the ones the bank reported.
    assert client.put(
        "/api/me/currency", headers=_auth(token), json={"currency": "RON"}
    ).status_code == 200
    user_id = _user_id(token)
    connection = BankConnection(
        user_id=user_id,
        provider="gocardless",
        institution_id="REVOLUT_REVOLT21",
        institution_name="Revolut",
        requisition_id="req-" + str(user_id),
        status="linked",
    )
    db.add(connection)
    db.commit()
    db.refresh(connection)

    account = BankAccount(
        user_id=user_id,
        connection_id=connection.id,
        external_id="acc-" + str(user_id),
        name="Revolut RON",
        currency="RON",
    )
    db.add(account)
    db.commit()
    db.refresh(connection)
    return connection


@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def use_this_modules_db():
    """
    Points the app at this module's database for the duration of each test.

    Every test module here installs its own get_db override at import time,
    so the last one imported wins for the whole session. That is harmless
    where a module only talks over HTTP, but these tests also hold a Session
    of their own and assert across both - so the override is (re)installed
    per test rather than once at import.
    """
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    yield
    # Put back whatever was there, so the modules that run after this one
    # keep the database they set up at import time.
    if previous is not None:
        app.dependency_overrides[get_db] = previous


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Nothing in these tests may reach the aggregator or BNR by accident."""
    monkeypatch.setattr(
        gocardless,
        "_access_token",
        lambda: pytest.fail("the aggregator was called for real"),
    )
    # Same-currency expenses never convert; the few that do get a fixed rate
    # so the assertions can be exact.
    monkeypatch.setattr(bnr, "convert", lambda amount, source, target: (amount * 5.0, 5.0))


# --- merchant normalisation ----------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("CARD PAYMENT TO LIDL 0412 BUCURESTI", "lidl bucuresti"),
        ("Lidl Sibiu", "lidl sibiu"),
        ("LIDL*2311", "lidl"),
        ("Plata card MEGA IMAGE", "mega image"),
        ("Cumparare POS Profi", "profi"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_merchant_strips_bank_noise(raw, expected):
    assert normalize_merchant(raw) == expected


def test_diacritics_fold_so_one_rule_covers_both_spellings():
    assert normalize_merchant("Farmacia Tei București") == normalize_merchant("Farmacia Tei Bucuresti")


# --- the category decision -----------------------------------------------


def test_keyword_hint_matches_the_users_own_category_name():
    assert suggest_category(
        merchant_key="lidl bucuresti",
        mcc=None,
        category_names=["Alimente", "Transport"],
        rules={},
    ) == "Alimente"


def test_mcc_covers_a_merchant_the_keyword_table_has_never_seen():
    assert suggest_category(
        merchant_key="magazin oarecare srl",
        mcc="5411",
        category_names=["Alimente", "Transport"],
        rules={},
    ) == "Alimente"


def test_a_learned_rule_beats_the_built_in_hint():
    # Lidl would be groceries by default; this user files it as Work lunch.
    assert suggest_category(
        merchant_key="lidl bucuresti",
        mcc="5411",
        category_names=["Alimente", "Work lunch"],
        rules={"lidl bucuresti": "Work lunch"},
    ) == "Work lunch"


def test_a_learned_rule_still_matches_when_the_bank_adds_a_branch():
    assert suggest_category(
        merchant_key="lidl cluj floresti",
        mcc=None,
        category_names=["Alimente", "Work lunch"],
        rules={"lidl": "Work lunch"},
    ) == "Work lunch"


def test_an_unknown_merchant_gets_no_guess():
    # The point of returning None: it goes to the inbox instead of silently
    # into whatever category happens to be closest.
    assert suggest_category(
        merchant_key="qwerty zxcv srl",
        mcc=None,
        category_names=["Alimente", "Transport"],
        rules={},
    ) is None


# --- the sync loop --------------------------------------------------------


def test_known_merchant_becomes_an_expense_on_its_own(db, monkeypatch):
    token = _signup("sync-known@example.com")
    category = _category(token, "Alimente")
    connection = _link(db, token)

    monkeypatch.setattr(
        gocardless,
        "fetch_transactions",
        lambda account_id, date_from=None: [_tx("t1", -42.5, "CARD PAYMENT TO LIDL 0412")],
    )

    summary = bank_sync.sync_connection(db, connection)
    assert summary.imported == 1
    assert summary.pending == 0

    expense = db.query(Expense).filter(Expense.user_id == connection.user_id).one()
    assert expense.amount == 42.5
    assert expense.category_id == category["id"]
    assert expense.source == "bank"


def test_unknown_merchant_waits_in_the_inbox(db, monkeypatch):
    token = _signup("sync-unknown@example.com")
    _category(token, "Alimente")
    connection = _link(db, token)

    monkeypatch.setattr(
        gocardless,
        "fetch_transactions",
        lambda account_id, date_from=None: [_tx("t2", -19.0, "ZXCV OARECARE SRL")],
    )

    summary = bank_sync.sync_connection(db, connection)
    assert (summary.imported, summary.pending) == (0, 1)
    assert db.query(Expense).filter(Expense.user_id == connection.user_id).count() == 0

    inbox = client.get("/api/bank/inbox", headers=_auth(token)).json()
    assert len(inbox) == 1
    assert inbox[0]["merchant"] == "Zxcv Oarecare Srl"
    assert inbox[0]["suggested_category_id"] is None


def test_incoming_money_is_never_an_expense(db, monkeypatch):
    token = _signup("sync-income@example.com")
    _category(token, "Alimente")
    connection = _link(db, token)

    monkeypatch.setattr(
        gocardless,
        "fetch_transactions",
        lambda account_id, date_from=None: [
            _tx("t3", 3000.0, "SALARY"),
            _tx("t4", -25.0, "Transfer to vault"),
        ],
    )

    summary = bank_sync.sync_connection(db, connection)
    assert summary.skipped == 2
    assert summary.imported == 0
    assert db.query(Expense).filter(Expense.user_id == connection.user_id).count() == 0


def test_re_running_a_sync_imports_nothing_twice(db, monkeypatch):
    token = _signup("sync-dedupe@example.com")
    _category(token, "Alimente")
    connection = _link(db, token)

    monkeypatch.setattr(
        gocardless,
        "fetch_transactions",
        lambda account_id, date_from=None: [_tx("t5", -10.0, "Lidl")],
    )

    first = bank_sync.sync_connection(db, connection)
    second = bank_sync.sync_connection(db, connection)

    assert first.imported == 1
    assert (second.imported, second.duplicates) == (0, 1)
    assert db.query(Expense).filter(Expense.user_id == connection.user_id).count() == 1


def test_a_transaction_with_no_id_still_dedupes(db, monkeypatch):
    token = _signup("sync-nofingerprint@example.com")
    _category(token, "Alimente")
    connection = _link(db, token)

    bare = {
        "bookingDate": "2026-10-21",
        "transactionAmount": {"amount": "-33.00", "currency": "RON"},
        "remittanceInformationUnstructured": "Lidl",
    }
    monkeypatch.setattr(gocardless, "fetch_transactions", lambda account_id, date_from=None: [bare])

    bank_sync.sync_connection(db, connection)
    second = bank_sync.sync_connection(db, connection)
    assert second.duplicates == 1


def test_another_currency_is_converted_and_keeps_the_original(db, monkeypatch):
    token = _signup("sync-fx@example.com")
    _category(token, "Alimente")
    connection = _link(db, token)

    monkeypatch.setattr(
        gocardless,
        "fetch_transactions",
        lambda account_id, date_from=None: [_tx("t6", -20.0, "Lidl", currency="EUR")],
    )

    bank_sync.sync_connection(db, connection)
    expense = db.query(Expense).filter(Expense.user_id == connection.user_id).one()
    assert expense.amount == 100.0  # 20 EUR at the fixture's 5.0
    assert (expense.original_amount, expense.original_currency, expense.fx_rate) == (20.0, "EUR", 5.0)


def test_no_rates_leaves_it_pending_rather_than_filing_a_wrong_number(db, monkeypatch):
    token = _signup("sync-norates@example.com")
    _category(token, "Alimente")
    connection = _link(db, token)

    def unavailable(amount, source, target):
        raise bnr.RatesUnavailable("no rates on disk")

    monkeypatch.setattr(bnr, "convert", unavailable)
    monkeypatch.setattr(
        gocardless,
        "fetch_transactions",
        lambda account_id, date_from=None: [_tx("t7", -20.0, "Lidl", currency="EUR")],
    )

    summary = bank_sync.sync_connection(db, connection)
    assert (summary.imported, summary.pending) == (0, 1)
    assert db.query(Expense).filter(Expense.user_id == connection.user_id).count() == 0


def test_an_expired_consent_is_recorded_rather_than_retried(db, monkeypatch):
    token = _signup("sync-expired@example.com")
    _category(token, "Alimente")
    connection = _link(db, token)

    def expired(account_id, date_from=None):
        raise gocardless.ConsentExpired("consent is no longer valid")

    monkeypatch.setattr(gocardless, "fetch_transactions", expired)

    summary = bank_sync.sync_connection(db, connection)
    assert summary.errors
    db.refresh(connection)
    assert connection.status == "expired"

    # And the app refuses a manual sync on it, pointing at the fix.
    response = client.post(
        "/api/bank/connections/{}/sync".format(connection.id), headers=_auth(token)
    )
    assert response.status_code == 409


# --- the confirm inbox ----------------------------------------------------


def test_filing_from_the_inbox_creates_the_expense_and_learns_the_merchant(db, monkeypatch):
    token = _signup("inbox-file@example.com")
    category = _category(token, "Haine")
    connection = _link(db, token)

    monkeypatch.setattr(
        gocardless,
        "fetch_transactions",
        lambda account_id, date_from=None: [_tx("t8", -89.0, "BOUTIQUE OARECARE")],
    )
    bank_sync.sync_connection(db, connection)

    inbox = client.get("/api/bank/inbox", headers=_auth(token)).json()
    response = client.post(
        "/api/bank/inbox/{}".format(inbox[0]["id"]),
        headers=_auth(token),
        json={"category_id": category["id"], "remember": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["remembered"] is True

    expense = db.query(Expense).filter(Expense.user_id == connection.user_id).one()
    assert expense.category_id == category["id"]
    assert expense.amount == 89.0

    rule = db.query(MerchantRule).filter(MerchantRule.user_id == connection.user_id).one()
    assert rule.pattern == "boutique oarecare"

    # The inbox is empty, and the learned rule shows up as one.
    assert client.get("/api/bank/inbox", headers=_auth(token)).json() == []
    rules = client.get("/api/bank/rules", headers=_auth(token)).json()
    assert rules[0]["category_name"] == "Haine"


def test_the_learned_rule_files_the_next_visit_without_asking(db, monkeypatch):
    token = _signup("inbox-learned@example.com")
    category = _category(token, "Haine")
    connection = _link(db, token)

    monkeypatch.setattr(
        gocardless,
        "fetch_transactions",
        lambda account_id, date_from=None: [_tx("t9", -89.0, "BOUTIQUE OARECARE")],
    )
    bank_sync.sync_connection(db, connection)
    inbox = client.get("/api/bank/inbox", headers=_auth(token)).json()
    client.post(
        "/api/bank/inbox/{}".format(inbox[0]["id"]),
        headers=_auth(token),
        json={"category_id": category["id"], "remember": True},
    )

    # Same merchant, a different branch, a new transaction id.
    monkeypatch.setattr(
        gocardless,
        "fetch_transactions",
        lambda account_id, date_from=None: [_tx("t10", -40.0, "BOUTIQUE OARECARE CLUJ", date="2026-10-22")],
    )
    summary = bank_sync.sync_connection(db, connection)

    assert (summary.imported, summary.pending) == (1, 0)
    amounts = sorted(
        expense.amount
        for expense in db.query(Expense).filter(Expense.user_id == connection.user_id).all()
    )
    assert amounts == [40.0, 89.0]


def test_filing_without_remember_writes_no_rule(db, monkeypatch):
    token = _signup("inbox-oneoff@example.com")
    category = _category(token, "Altele")
    connection = _link(db, token)

    monkeypatch.setattr(
        gocardless,
        "fetch_transactions",
        lambda account_id, date_from=None: [_tx("t11", -5.0, "CEVA UNIC SRL")],
    )
    bank_sync.sync_connection(db, connection)

    inbox = client.get("/api/bank/inbox", headers=_auth(token)).json()
    client.post(
        "/api/bank/inbox/{}".format(inbox[0]["id"]),
        headers=_auth(token),
        json={"category_id": category["id"], "remember": False},
    )
    assert db.query(MerchantRule).filter(MerchantRule.user_id == connection.user_id).count() == 0


def test_ignoring_a_transaction_takes_it_out_of_the_inbox_for_good(db, monkeypatch):
    token = _signup("inbox-ignore@example.com")
    _category(token, "Alimente")
    connection = _link(db, token)

    monkeypatch.setattr(
        gocardless,
        "fetch_transactions",
        lambda account_id, date_from=None: [_tx("t12", -7.0, "NECUNOSCUT SRL")],
    )
    bank_sync.sync_connection(db, connection)

    inbox = client.get("/api/bank/inbox", headers=_auth(token)).json()
    assert client.delete(
        "/api/bank/inbox/{}".format(inbox[0]["id"]), headers=_auth(token)
    ).status_code == 200
    assert client.get("/api/bank/inbox", headers=_auth(token)).json() == []

    # A later sync re-offers nothing: the row is still there, just dismissed.
    assert bank_sync.sync_connection(db, connection).duplicates == 1


# --- isolation and tear-down ---------------------------------------------


def test_one_users_inbox_is_not_another_users(db, monkeypatch):
    owner = _signup("inbox-owner@example.com")
    stranger = _signup("inbox-stranger@example.com")
    _category(owner, "Alimente")
    connection = _link(db, owner)

    monkeypatch.setattr(
        gocardless,
        "fetch_transactions",
        lambda account_id, date_from=None: [_tx("t13", -8.0, "NECUNOSCUT DOI SRL")],
    )
    bank_sync.sync_connection(db, connection)

    row_id = client.get("/api/bank/inbox", headers=_auth(owner)).json()[0]["id"]
    assert client.get("/api/bank/inbox", headers=_auth(stranger)).json() == []
    assert client.delete(
        "/api/bank/inbox/{}".format(row_id), headers=_auth(stranger)
    ).status_code == 404
    assert client.post(
        "/api/bank/connections/{}/sync".format(connection.id), headers=_auth(stranger)
    ).status_code == 404


def test_disconnecting_keeps_the_expenses_and_drops_the_bank_rows(db, monkeypatch):
    token = _signup("disconnect@example.com")
    _category(token, "Alimente")
    connection = _link(db, token)
    user_id = connection.user_id

    monkeypatch.setattr(
        gocardless,
        "fetch_transactions",
        lambda account_id, date_from=None: [_tx("t14", -12.0, "Lidl")],
    )
    bank_sync.sync_connection(db, connection)

    assert client.delete(
        "/api/bank/connections/{}".format(connection.id), headers=_auth(token)
    ).status_code == 200

    assert db.query(Expense).filter(Expense.user_id == user_id).count() == 1
    assert db.query(BankTransaction).filter(BankTransaction.user_id == user_id).count() == 0
    assert db.query(BankConnection).filter(BankConnection.user_id == user_id).count() == 0


# --- the scheduled endpoint ----------------------------------------------


def test_scheduled_sync_is_closed_unless_a_secret_is_configured(monkeypatch):
    # The in-memory database is shared across this module, so a successful
    # call here walks every connection the other tests left behind.
    monkeypatch.setattr(gocardless, "fetch_transactions", lambda account_id, date_from=None: [])
    monkeypatch.delenv("CRON_SECRET", raising=False)
    assert client.post("/api/bank/sync-all").status_code == 404

    monkeypatch.setenv("CRON_SECRET", "s3cret")
    assert client.post("/api/bank/sync-all").status_code == 401
    assert client.post(
        "/api/bank/sync-all", headers={"X-Cron-Secret": "wrong"}
    ).status_code == 401
    assert client.post(
        "/api/bank/sync-all", headers={"X-Cron-Secret": "s3cret"}
    ).status_code == 200


def test_the_bank_panel_is_hidden_when_the_server_has_no_credentials(monkeypatch):
    token = _signup("status@example.com")
    monkeypatch.delenv("GOCARDLESS_SECRET_ID", raising=False)
    monkeypatch.delenv("GOCARDLESS_SECRET_KEY", raising=False)

    body = client.get("/api/bank/status", headers=_auth(token)).json()
    assert body["configured"] is False
