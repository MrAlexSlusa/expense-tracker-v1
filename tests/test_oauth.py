"""
Social sign-in: the parts that don't need a live provider - which providers
get advertised, that a tampered or unlisted redirect target is refused, and
that a completed exchange lands on the right User row.

The provider round trip itself (app/oauth.py's exchange_code / fetch_identity)
is stubbed, since the interesting behaviour here is what this app does with an
identity once it has one, not httpx.
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
from app.models import User
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


# Every test module here overrides get_db at import time, so the last one
# imported would otherwise own the override for the whole run. This file reads
# its own database directly (to count User rows), so it claims the override for
# the duration of each of its tests and hands it back afterwards.
@pytest.fixture(autouse=True)
def use_this_modules_db():
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    yield
    if previous is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous

FRONTEND = "http://localhost:5500/index.html"


@pytest.fixture
def google_configured(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id-123")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret-456")
    yield


def test_providers_list_is_empty_until_credentials_are_set(monkeypatch):
    for var in ("GOOGLE_CLIENT_ID", "GITHUB_CLIENT_ID", "APPLE_CLIENT_ID"):
        monkeypatch.delenv(var, raising=False)
    assert client.get("/api/auth/providers").json() == {"providers": []}


def test_configured_provider_is_advertised_and_starts_a_redirect(google_configured):
    listed = client.get("/api/auth/providers").json()["providers"]
    assert listed == [{"name": "google", "label": "Google"}]

    r = client.get(
        "/api/auth/oauth/google/start",
        params={"redirect_uri": FRONTEND},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert r.headers["location"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=client-id-123" in r.headers["location"]


def test_unconfigured_provider_cannot_be_started(monkeypatch):
    monkeypatch.delenv("APPLE_CLIENT_ID", raising=False)
    r = client.get("/api/auth/oauth/apple/start", params={"redirect_uri": FRONTEND})
    assert r.status_code == 404


def test_redirect_target_outside_the_allowlist_is_refused(google_configured):
    r = client.get(
        "/api/auth/oauth/google/start",
        params={"redirect_uri": "https://attacker.example/steal"},
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_allowlisted_origin_from_the_environment_is_accepted(google_configured, monkeypatch):
    monkeypatch.setenv("OAUTH_ALLOWED_ORIGINS", "https://mralexslusa.github.io")
    r = client.get(
        "/api/auth/oauth/google/start",
        params={"redirect_uri": "https://mralexslusa.github.io/expense-tracker-v1/"},
        follow_redirects=False,
    )
    assert r.status_code == 302


def test_callback_with_a_forged_state_is_refused(google_configured):
    r = client.get(
        "/api/auth/oauth/google/callback",
        params={"code": "abc", "state": "not-a-real-state"},
        follow_redirects=False,
    )
    assert r.status_code == 400


def _complete(monkeypatch, email, name=None):
    monkeypatch.setattr(oauth, "exchange_code", lambda *a, **kw: {"access_token": "t"})
    monkeypatch.setattr(oauth, "fetch_identity", lambda *a, **kw: (email, "sub-1", name))
    return client.get(
        "/api/auth/oauth/google/callback",
        params={"code": "abc", "state": oauth.encode_state("google", FRONTEND)},
        follow_redirects=False,
    )


def test_first_google_sign_in_creates_an_account_and_hands_back_a_token(google_configured, monkeypatch):
    r = _complete(monkeypatch, "new-person@example.com", "New Person")
    assert r.status_code == 302
    assert r.headers["location"].startswith(FRONTEND + "#token=")

    token = r.headers["location"].split("#token=")[1]
    me = client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["email"] == "new-person@example.com"
    assert me["oauth_provider"] == "google"
    assert me["has_password"] is False
    assert me["onboarded"] is False  # the signup quiz still runs


def test_google_sign_in_reuses_the_password_account_with_the_same_email(google_configured, monkeypatch):
    signup = client.post(
        "/api/auth/signup",
        json={"email": "both@example.com", "password": "hunter2222"},
    )
    assert signup.status_code == 200

    r = _complete(monkeypatch, "both@example.com")
    token = r.headers["location"].split("#token=")[1]
    me = client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).json()

    db = TestingSessionLocal()
    try:
        assert db.query(User).filter(User.email == "both@example.com").count() == 1
    finally:
        db.close()
    assert me["oauth_provider"] == "google"
    assert me["has_password"] is True  # the password still works too


def test_a_provider_failure_comes_back_as_an_error_on_the_frontend_url(google_configured, monkeypatch):
    def boom(*args, **kwargs):
        raise oauth.OAuthError("The sign-in provider rejected this attempt")

    monkeypatch.setattr(oauth, "exchange_code", boom)
    r = client.get(
        "/api/auth/oauth/google/callback",
        params={"code": "abc", "state": oauth.encode_state("google", FRONTEND)},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert r.headers["location"].startswith(FRONTEND + "#oauth_error=")
