"""
Client for GoCardless Bank Account Data (the former Nordigen) - the
open-banking route into a *personal* Revolut account.

Why this and not Revolut's own API: Revolut only publishes an API for
Revolut Business. A personal account is reachable only as a PSD2 account
information service, and GoCardless is a licensed AISP with a free tier that
covers Revolut in Romania, so the app never has to hold bank credentials or
become licensed itself.

The flow, which the helpers below mirror:

    create_link()        -> POST /agreements + /requisitions, returns a
                            hosted URL where the user authenticates with
                            Revolut
    (user authenticates, bank redirects back with ?ref=<our reference>)
    fetch_accounts()     -> GET /requisitions/{id}, now populated
    fetch_transactions() -> GET /accounts/{id}/transactions

Two things about this API shape the code:

- Access tokens are short-lived and minted from a secret pair rather than
  refreshed per user, so one process-wide cached token serves every user.
  _access_token() handles that; nothing else here thinks about auth.
- Consent is capped at 90 days by PSD2, after which every call for that
  requisition fails until the user re-authenticates. That is not an error to
  retry, it is a state the user has to resolve, so it surfaces as
  ConsentExpired rather than being folded into the generic failure.
"""

import os
import time
from dataclasses import dataclass
from typing import Optional

import httpx

BASE_URL = os.environ.get("GOCARDLESS_BASE_URL", "https://bankaccountdata.gocardless.com/api/v2")

# PSD2 ceilings. Asking for more than the bank allows gets the whole
# agreement rejected, so these are the maximums rather than wishes.
MAX_HISTORICAL_DAYS = 90
ACCESS_VALID_FOR_DAYS = 90

TIMEOUT = httpx.Timeout(30.0)


class BankApiError(RuntimeError):
    """Any failure from the aggregator that is not specifically consent."""


class NotConfigured(BankApiError):
    """No GOCARDLESS_SECRET_ID / _KEY in the environment."""


class ConsentExpired(BankApiError):
    """
    The 90-day window closed (or the user revoked access). Retrying is
    pointless - the user has to go through create_link() again.
    """


@dataclass
class Institution:
    id: str
    name: str
    logo: Optional[str] = None


@dataclass
class LinkRequest:
    requisition_id: str
    link: str
    agreement_id: Optional[str]


@dataclass
class RemoteAccount:
    external_id: str
    name: Optional[str] = None
    iban: Optional[str] = None
    currency: Optional[str] = None


def is_configured() -> bool:
    return bool(os.environ.get("GOCARDLESS_SECRET_ID") and os.environ.get("GOCARDLESS_SECRET_KEY"))


# (token, unix expiry). Process-wide on purpose: the token identifies the app,
# not a user, so minting one per request would just burn rate limit.
_token_cache: tuple = (None, 0.0)


def _access_token() -> str:
    global _token_cache
    token, expires_at = _token_cache
    # 60s of slack so a token cannot expire between this check and the call.
    if token and expires_at - 60 > time.time():
        return token

    secret_id = os.environ.get("GOCARDLESS_SECRET_ID")
    secret_key = os.environ.get("GOCARDLESS_SECRET_KEY")
    if not secret_id or not secret_key:
        raise NotConfigured("GOCARDLESS_SECRET_ID / GOCARDLESS_SECRET_KEY are not set")

    try:
        response = httpx.post(
            BASE_URL + "/token/new/",
            json={"secret_id": secret_id, "secret_key": secret_key},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise BankApiError("Could not reach the bank data provider: {}".format(exc)) from exc

    if response.status_code >= 400:
        raise BankApiError("Bank data provider rejected the credentials ({})".format(response.status_code))

    payload = response.json()
    token = payload.get("access")
    if not token:
        raise BankApiError("Bank data provider returned no access token")

    _token_cache = (token, time.time() + float(payload.get("access_expires", 3600)))
    return token


def _detail(response: httpx.Response) -> Optional[str]:
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    for key in ("summary", "detail", "message"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _request(method: str, path: str, **kwargs) -> dict:
    try:
        response = httpx.request(
            method,
            BASE_URL + path,
            headers={"Authorization": "Bearer " + _access_token(), "Accept": "application/json"},
            timeout=TIMEOUT,
            **kwargs,
        )
    except httpx.HTTPError as exc:
        raise BankApiError("Could not reach the bank data provider: {}".format(exc)) from exc

    if response.status_code == 204:
        return {}

    # The provider signals a dead consent with a 401/403 on the requisition
    # or account. Treating a plain 401 as consent trouble is deliberate: our
    # own app token is minted fresh above, so an auth failure at this point
    # is about the bank link, not about us.
    if response.status_code in (401, 403):
        raise ConsentExpired(_detail(response) or "The bank connection needs to be renewed")

    if response.status_code >= 400:
        raise BankApiError(_detail(response) or "Bank data provider error ({})".format(response.status_code))

    return response.json()


def list_institutions(country: str = "RO") -> list:
    payload = _request("GET", "/institutions/?country=" + country.lower())
    if not isinstance(payload, list):
        return []
    return [
        Institution(id=item["id"], name=item.get("name", item["id"]), logo=item.get("logo"))
        for item in payload
        if item.get("id")
    ]


def create_link(*, institution_id: str, redirect_url: str, reference: str, language: str = "ro") -> LinkRequest:
    """
    Opens a consent request and returns the URL to send the user to.

    `reference` comes back to us on the redirect and is the only thing tying
    that bare browser hit to a user, so the caller passes a signed value
    rather than a guessable id (see app/bank_api.py).
    """
    try:
        agreement = _request(
            "POST",
            "/agreements/enduser/",
            json={
                "institution_id": institution_id,
                "max_historical_days": MAX_HISTORICAL_DAYS,
                "access_valid_for_days": ACCESS_VALID_FOR_DAYS,
                "access_scope": ["balances", "details", "transactions"],
            },
        )
        agreement_id = agreement.get("id")
    except BankApiError:
        # Some institutions refuse a custom agreement (shorter history, fewer
        # scopes). The requisition still works without one, on the bank's own
        # defaults, which beats refusing to link at all.
        agreement_id = None

    body = {
        "redirect": redirect_url,
        "institution_id": institution_id,
        "reference": reference,
        "user_language": language.upper(),
    }
    if agreement_id:
        body["agreement"] = agreement_id

    requisition = _request("POST", "/requisitions/", json=body)
    link = requisition.get("link")
    requisition_id = requisition.get("id")
    if not link or not requisition_id:
        raise BankApiError("Bank data provider returned no consent link")

    return LinkRequest(requisition_id=requisition_id, link=link, agreement_id=agreement_id)


def fetch_accounts(requisition_id: str) -> list:
    """
    The account ids behind a finished consent, with whatever naming detail
    the bank exposes.

    Details are fetched per account and are allowed to fail: a missing name
    costs a nicer label, while refusing the whole link over it would cost
    the connection.
    """
    requisition = _request("GET", "/requisitions/" + requisition_id + "/")
    status = (requisition.get("status") or "").upper()
    # LN = linked. EX / RJ / SU mean the consent expired, was rejected, or
    # was abandoned - all of which need a new link, not a retry.
    if status in ("EX", "RJ", "SU"):
        raise ConsentExpired("The bank connection is no longer valid (status {})".format(status))

    accounts = []
    for account_id in requisition.get("accounts") or []:
        account = RemoteAccount(external_id=account_id)
        try:
            details = _request("GET", "/accounts/" + account_id + "/details/").get("account") or {}
            account.name = details.get("name") or details.get("product") or details.get("ownerName")
            account.iban = details.get("iban")
            account.currency = (details.get("currency") or "").upper() or None
        except BankApiError:
            pass
        accounts.append(account)
    return accounts


def fetch_transactions(account_id: str, *, date_from: Optional[str] = None) -> list:
    """
    Booked transactions for one account, as the provider sends them.
    `date_from` is "YYYY-MM-DD".

    Pending (not yet booked) transactions are deliberately dropped: their
    ids change once they settle, so importing them would either duplicate
    the expense or strand it under an id that never appears again.
    """
    query = "?date_from=" + date_from if date_from else ""
    payload = _request("GET", "/accounts/" + account_id + "/transactions/" + query)
    booked = ((payload.get("transactions") or {}).get("booked")) or []
    return [tx for tx in booked if isinstance(tx, dict)]
