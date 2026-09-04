"""
Social sign-in (Google, Apple, GitHub) as a third identity path alongside the
email/password accounts in app/auth.py and the WhatsApp phone numbers in
app/webhook.py. All three land on the same User row, matched by verified
email address, so signing in with Google to an account that was created with
a password gets you that same account rather than a duplicate.

The flow is server-side authorization code, not a browser-side implicit grant,
because the frontend is a static bundle on GitHub Pages: it can't hold a client
secret, and the backend already owns the JWT the app runs on. So:

    frontend  -> GET  /api/auth/oauth/{provider}/start?redirect_uri=...
              -> 302 to the provider
    provider  -> GET  /api/auth/oauth/{provider}/callback?code&state
              -> 302 back to redirect_uri with #token=<app JWT>

`state` is a short-lived signed token carrying the provider and the frontend
URL to come back to, which is what keeps the callback from being replayable
and keeps `redirect_uri` from being tampered with in flight. It's checked
against an allowlist on the way in as well - an unvalidated redirect here
would hand the access token to whoever asked for it.

Every provider is optional: one is "configured" only once its client id and
secret are in the environment, and GET /api/auth/providers tells the frontend
which buttons to draw. Nothing here runs at import time, so a deploy with no
OAuth credentials at all behaves exactly as it did before.
"""

import os
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode, urlparse

import httpx
from jose import JWTError, jwt

from app.auth import ALGORITHM, SECRET_KEY

STATE_EXPIRE_SECONDS = 600  # a user has 10 minutes to finish at the provider


@dataclass(frozen=True)
class Provider:
    name: str
    label: str
    authorize_url: str
    token_url: str
    scope: str
    # Apple returns the email inside the id_token and POSTs its callback;
    # Google and GitHub are fetched from a userinfo endpoint over GET.
    userinfo_url: Optional[str] = None
    form_post: bool = False


PROVIDERS = {
    "google": Provider(
        name="google",
        label="Google",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
        scope="openid email profile",
    ),
    "github": Provider(
        name="github",
        label="GitHub",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        userinfo_url="https://api.github.com/user",
        scope="read:user user:email",
    ),
    "apple": Provider(
        name="apple",
        label="Apple",
        authorize_url="https://appleid.apple.com/auth/authorize",
        token_url="https://appleid.apple.com/auth/token",
        scope="name email",
        form_post=True,  # Apple only sends email scope back via response_mode=form_post
    ),
}


class OAuthError(Exception):
    """Anything that went wrong talking to a provider - surfaced to the user as one message."""


# --- configuration --------------------------------------------------------


def _env(provider: str, key: str) -> str:
    return (os.environ.get(f"{provider.upper()}_{key}") or "").strip()


def client_id(provider: str) -> str:
    return _env(provider, "CLIENT_ID")


def is_configured(provider: str) -> bool:
    if provider not in PROVIDERS:
        return False
    if provider == "apple":
        # Apple has no static secret: it's a signed JWT built from a .p8 key.
        return bool(client_id("apple") and _env("apple", "TEAM_ID")
                    and _env("apple", "KEY_ID") and _env("apple", "PRIVATE_KEY"))
    return bool(client_id(provider) and _env(provider, "CLIENT_SECRET"))


def enabled_providers() -> list[dict]:
    return [
        {"name": p.name, "label": p.label}
        for p in PROVIDERS.values()
        if is_configured(p.name)
    ]


def _client_secret(provider: str) -> str:
    """
    Apple's "client secret" is an ES256 JWT signed with the private key from
    the Apple developer console, valid for at most 6 months; it's cheap enough
    to mint per request rather than cache and have to reason about expiry.
    """
    if provider != "apple":
        return _env(provider, "CLIENT_SECRET")

    now = int(time.time())
    # Render (and .env files) can't hold real newlines in a value, so the key
    # is stored with literal \n and unescaped here.
    private_key = _env("apple", "PRIVATE_KEY").replace("\\n", "\n")
    return jwt.encode(
        {
            "iss": _env("apple", "TEAM_ID"),
            "iat": now,
            "exp": now + 3600,
            "aud": "https://appleid.apple.com",
            "sub": client_id("apple"),
        },
        private_key,
        algorithm="ES256",
        headers={"kid": _env("apple", "KEY_ID")},
    )


# --- redirect targets -----------------------------------------------------


def _allowed_origins() -> set[str]:
    """
    Where a sign-in is allowed to hand the token back to. CORS is wide open on
    this API by design (see app/main.py), but that only governs who may read a
    response - a redirect target is different, since the token travels in the
    URL. So this is its own, explicit list.
    """
    configured = os.environ.get("OAUTH_ALLOWED_ORIGINS", "")
    origins = {o.strip().rstrip("/") for o in configured.split(",") if o.strip()}
    origins.update({
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
    })
    return origins


def check_redirect(redirect_uri: str) -> str:
    parsed = urlparse(redirect_uri)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise OAuthError("Invalid redirect target")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin not in _allowed_origins():
        raise OAuthError("This site isn't allowed to complete a social sign-in")
    # Drop any query/fragment the caller sent - the token is appended as the
    # fragment on the way back, and a caller-supplied one would collide with it.
    return f"{origin}{parsed.path}"


def callback_url(provider: str, base_url: str) -> str:
    """The URL registered with the provider - always this API's own callback."""
    explicit = os.environ.get("OAUTH_CALLBACK_BASE_URL", "").strip().rstrip("/")
    base = explicit or base_url.rstrip("/")
    return f"{base}/api/auth/oauth/{provider}/callback"


# --- state token ----------------------------------------------------------


def encode_state(provider: str, redirect_uri: str) -> str:
    return jwt.encode(
        {"provider": provider, "redirect_uri": redirect_uri,
         "exp": int(time.time()) + STATE_EXPIRE_SECONDS},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def decode_state(provider: str, state: str) -> str:
    """Returns the redirect_uri the flow started from, or raises."""
    try:
        payload = jwt.decode(state, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise OAuthError("This sign-in link has expired - start again")
    if payload.get("provider") != provider:
        raise OAuthError("This sign-in link doesn't match the provider that answered")
    return check_redirect(payload.get("redirect_uri") or "")


# --- the provider round trip ----------------------------------------------


def authorize_url(provider: str, redirect_uri: str, state: str) -> str:
    spec = PROVIDERS[provider]
    params = {
        "client_id": client_id(provider),
        "redirect_uri": redirect_uri,
        "scope": spec.scope,
        "response_type": "code",
        "state": state,
    }
    if spec.form_post:
        params["response_mode"] = "form_post"
    if provider == "google":
        # Without this Google silently reuses the last account on a shared
        # browser instead of asking which one to sign in with.
        params["prompt"] = "select_account"
    return f"{spec.authorize_url}?{urlencode(params)}"


def exchange_code(provider: str, code: str, redirect_uri: str) -> dict:
    spec = PROVIDERS[provider]
    try:
        response = httpx.post(
            spec.token_url,
            data={
                "client_id": client_id(provider),
                "client_secret": _client_secret(provider),
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
            timeout=15,
        )
    except httpx.HTTPError:
        raise OAuthError("Couldn't reach the sign-in provider - try again")
    if response.status_code >= 400:
        raise OAuthError("The sign-in provider rejected this attempt")
    return response.json()


def fetch_identity(provider: str, tokens: dict) -> tuple[str, str, Optional[str]]:
    """
    Returns (email, subject id, display name). The email has to be one the
    provider says it verified - an unverified address would let anyone claim
    an existing account here by signing up elsewhere with the same address.
    """
    if provider == "apple":
        return _apple_identity(tokens)
    if provider == "google":
        return _google_identity(tokens)
    return _github_identity(tokens)


def _google_identity(tokens: dict) -> tuple[str, str, Optional[str]]:
    profile = _get_json(
        PROVIDERS["google"].userinfo_url,
        headers={"Authorization": f"Bearer {tokens.get('access_token')}"},
    )
    email = (profile.get("email") or "").lower()
    if not email or not profile.get("email_verified"):
        raise OAuthError("Google didn't return a verified email address")
    return email, str(profile.get("sub") or email), profile.get("name")


def _github_identity(tokens: dict) -> tuple[str, str, Optional[str]]:
    headers = {
        "Authorization": f"Bearer {tokens.get('access_token')}",
        "Accept": "application/vnd.github+json",
    }
    profile = _get_json(PROVIDERS["github"].userinfo_url, headers=headers)
    # GitHub's /user only carries the public email, which is usually null, so
    # the verified primary address comes from the dedicated endpoint.
    emails = _get_json("https://api.github.com/user/emails", headers=headers)
    primary = next(
        (e for e in emails if isinstance(e, dict) and e.get("primary") and e.get("verified")),
        None,
    )
    if primary is None:
        raise OAuthError("GitHub didn't return a verified email address")
    return primary["email"].lower(), str(profile.get("id") or primary["email"]), profile.get("name")


def _apple_identity(tokens: dict) -> tuple[str, str, Optional[str]]:
    id_token = tokens.get("id_token")
    if not id_token:
        raise OAuthError("Apple didn't return an identity token")
    # The token came straight from Apple's token endpoint over TLS in response
    # to our own client secret, so its contents are already trusted; verifying
    # the signature here would mean fetching and caching Apple's JWKS for no
    # additional guarantee on this path.
    claims = jwt.get_unverified_claims(id_token)
    email = (claims.get("email") or "").lower()
    if not email:
        raise OAuthError("Apple didn't return an email address")
    verified = claims.get("email_verified")
    if verified is False or verified == "false":
        raise OAuthError("Apple didn't return a verified email address")
    return email, str(claims.get("sub") or email), None


def _get_json(url: str, headers: dict):
    try:
        response = httpx.get(url, headers=headers, timeout=15)
    except httpx.HTTPError:
        raise OAuthError("Couldn't reach the sign-in provider - try again")
    if response.status_code >= 400:
        raise OAuthError("The sign-in provider wouldn't share your account details")
    return response.json()
