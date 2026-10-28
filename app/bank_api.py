"""
The bank-connection endpoints: link a bank, sync it, and work the confirm
inbox.

Kept in its own router rather than added to app/api.py because the consent
round trip has a shape nothing else in the API has - one endpoint is hit by
the bank's redirect rather than by the app, with no token on it - and that
is easier to reason about in one place.

    POST   /api/bank/connect            -> { link } to send the user to
    GET    /api/bank/callback?ref=      <- the bank redirects here
    GET    /api/bank/connections        -> state, consent expiry, accounts
    POST   /api/bank/connections/{id}/sync
    DELETE /api/bank/connections/{id}
    GET    /api/bank/inbox              -> transactions awaiting a category
    POST   /api/bank/inbox/{id}         -> file one (and learn the merchant)
    DELETE /api/bank/inbox/{id}         -> ignore one
    GET    /api/bank/rules              -> learned merchants
    DELETE /api/bank/rules/{id}
"""

import os
import secrets
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import bank_sync, gocardless, oauth
from app.auth import get_current_user
from app.categorizer import suggest_category
from app.database import get_db
from app.models import (
    BankAccount,
    BankConnection,
    BankTransaction,
    BudgetCategory,
    Expense,
    MerchantRule,
    User,
)

router = APIRouter(prefix="/api/bank")

# Revolut's own ids at GoCardless. Which one a country gets varies, so the
# institution list is still the source of truth - this only decides what to
# float to the top of it.
REVOLUT_PREFIX = "REVOLUT"


class ConnectRequest(BaseModel):
    institution_id: str
    # Where to send the user after the bank is done. Checked against the same
    # allowlist as social sign-in: an open redirect here would be handing a
    # finished bank consent to whoever asked.
    redirect_uri: str
    country: str = "RO"
    language: str = "ro"


class FileTransactionRequest(BaseModel):
    category_id: int
    # Write a rule so this merchant files itself next time. On by default -
    # that is the whole point of the inbox - but a one-off purchase from a
    # merchant that could belong anywhere can opt out.
    remember: bool = True


def _bank_error(exc: Exception) -> HTTPException:
    if isinstance(exc, gocardless.NotConfigured):
        return HTTPException(
            status_code=503,
            detail="Bank sync isn't set up on the server yet (GOCARDLESS_SECRET_ID / _KEY)",
        )
    if isinstance(exc, gocardless.ConsentExpired):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


def _own_connection(db: Session, user: User, connection_id: int) -> BankConnection:
    connection = (
        db.query(BankConnection)
        .filter(BankConnection.id == connection_id, BankConnection.user_id == user.id)
        .first()
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Bank connection not found")
    return connection


def _connection_to_dict(connection: BankConnection) -> dict:
    return {
        "id": connection.id,
        "institution_id": connection.institution_id,
        "institution_name": connection.institution_name or connection.institution_id,
        "status": connection.status,
        "consent_expires_at": (
            connection.consent_expires_at.strftime("%Y-%m-%d") if connection.consent_expires_at else None
        ),
        "days_left": _days_left(connection),
        "last_synced_at": (
            connection.last_synced_at.strftime("%Y-%m-%d %H:%M") if connection.last_synced_at else None
        ),
        "last_error": connection.last_error,
        "accounts": [
            {
                "id": account.id,
                "name": account.name or account.currency or "Account",
                "currency": account.currency,
                "iban": account.iban,
                "enabled": account.enabled,
            }
            for account in connection.accounts
        ],
    }


def _days_left(connection: BankConnection) -> Optional[int]:
    if not connection.consent_expires_at:
        return None
    return max(0, (connection.consent_expires_at - datetime.utcnow()).days)


@router.get("/status")
def bank_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """One call for the whole bank panel: is it available, what is linked, how much is waiting."""
    connections = db.query(BankConnection).filter(BankConnection.user_id == user.id).all()
    pending = (
        db.query(BankTransaction)
        .filter(BankTransaction.user_id == user.id, BankTransaction.status == "pending")
        .count()
    )
    return {
        "configured": gocardless.is_configured(),
        "connections": [_connection_to_dict(connection) for connection in connections],
        "pending": pending,
    }


@router.get("/institutions")
def list_institutions(
    country: str = "RO",
    user: User = Depends(get_current_user),
):
    """
    The banks available in a country, Revolut first.

    Sorted that way rather than filtered to Revolut alone: the same consent
    machinery works for any PSD2 bank, and hiding the rest would mean
    rewriting this the first time a second account gets added.
    """
    try:
        institutions = gocardless.list_institutions(country)
    except gocardless.BankApiError as exc:
        raise _bank_error(exc)

    def sort_key(institution):
        return (0 if institution.id.upper().startswith(REVOLUT_PREFIX) else 1, institution.name.lower())

    return [
        {"id": institution.id, "name": institution.name, "logo": institution.logo}
        for institution in sorted(institutions, key=sort_key)
    ]


@router.post("/connect")
def connect_bank(
    payload: ConnectRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Starts a consent and returns the hosted URL to open.

    The row is written before the user leaves, in "pending", so a consent
    that is started and abandoned is visible as such instead of vanishing.
    """
    try:
        redirect_uri = oauth.check_redirect(payload.redirect_uri)
    except oauth.OAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    reference = secrets.token_urlsafe(24)
    callback = _callback_url(request)

    try:
        link = gocardless.create_link(
            institution_id=payload.institution_id,
            redirect_url=callback,
            reference=reference,
            language=payload.language,
        )
    except gocardless.BankApiError as exc:
        raise _bank_error(exc)

    connection = BankConnection(
        user_id=user.id,
        provider="gocardless",
        institution_id=payload.institution_id,
        requisition_id=link.requisition_id,
        agreement_id=link.agreement_id,
        reference=reference,
        redirect_uri=redirect_uri,
        status="pending",
        consent_expires_at=datetime.utcnow() + timedelta(days=gocardless.ACCESS_VALID_FOR_DAYS),
    )
    db.add(connection)
    db.commit()
    db.refresh(connection)

    return {"connection_id": connection.id, "link": link.link}


def _callback_url(request: Request) -> str:
    """
    This API's own callback, which is what the bank is told to return to.

    Reuses OAUTH_CALLBACK_BASE_URL because it answers the same question -
    what this backend looks like from outside a proxy - and having two env
    vars that must agree is a way to have them disagree.
    """
    explicit = os.environ.get("OAUTH_CALLBACK_BASE_URL", "").strip().rstrip("/")
    base = explicit or str(request.base_url).rstrip("/")
    return base + "/api/bank/callback"


@router.get("/callback")
def bank_callback(ref: str = "", error: str = "", db: Session = Depends(get_db)):
    """
    Where the bank sends the browser once the user has authenticated.

    No token on this request - the `ref` is what identifies the connection,
    which is why it is a random, single-purpose value. The response is always
    a redirect back into the app with a short status in the fragment, so the
    user never sees a bare JSON body.
    """
    connection = (
        db.query(BankConnection).filter(BankConnection.reference == ref).first() if ref else None
    )
    if connection is None:
        raise HTTPException(status_code=400, detail="This bank link has expired - start again from the app")

    target = connection.redirect_uri or "/"

    if error:
        connection.status = "error"
        connection.last_error = error
        db.commit()
        return RedirectResponse(_with_status(target, "error", error))

    try:
        accounts = bank_sync.refresh_accounts(db, connection)
    except gocardless.ConsentExpired as exc:
        connection.status = "expired"
        connection.last_error = str(exc)
        db.commit()
        return RedirectResponse(_with_status(target, "expired", str(exc)))
    except gocardless.BankApiError as exc:
        connection.status = "error"
        connection.last_error = str(exc)
        db.commit()
        return RedirectResponse(_with_status(target, "error", str(exc)))

    if not accounts:
        # Some banks redirect before provisioning finishes. The connection is
        # left pending so the next sync picks the accounts up, rather than
        # being marked broken.
        return RedirectResponse(_with_status(target, "pending", ""))

    # First sync runs here so the user comes back to a filled-in budget
    # rather than an empty panel and a button.
    summary = bank_sync.sync_connection(db, connection)
    return RedirectResponse(_with_status(target, "linked", "", imported=summary.imported, pending=summary.pending))


def _with_status(target: str, state: str, message: str, *, imported: int = 0, pending: int = 0) -> str:
    """
    Appends the outcome as a fragment, not a query string.

    A fragment never reaches the server logs of whatever is hosting the
    frontend, and this carries the bank's own error text.
    """
    fragment = "bank=" + state
    if imported or pending:
        fragment += "&imported={}&pending={}".format(imported, pending)
    if message:
        fragment += "&message=" + quote(message[:200])
    separator = "" if urlparse(target).fragment else "#"
    return target + separator + fragment


@router.post("/sync-all")
def sync_everything(request: Request, db: Session = Depends(get_db)):
    """
    Syncs every linked connection, for the scheduler rather than for a user.

    Authenticated with a shared secret header instead of a user token,
    because there is no user on a cron run - and gated on CRON_SECRET being
    set, so a deploy that never configured one has no open endpoint sitting
    there. scripts/sync_banks.py does the same work in-process if you would
    rather run it as a Render cron job than over HTTP.
    """
    secret = os.environ.get("CRON_SECRET", "").strip()
    if not secret:
        raise HTTPException(status_code=404, detail="Scheduled sync is not enabled on this deployment")
    # compare_digest rather than == so the check does not leak the secret
    # one character at a time through its own timing.
    presented = request.headers.get("X-Cron-Secret", "")
    if not secrets.compare_digest(presented, secret):
        raise HTTPException(status_code=401, detail="Invalid cron secret")

    return bank_sync.sync_all(db)


@router.get("/connections")
def list_connections(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    connections = db.query(BankConnection).filter(BankConnection.user_id == user.id).all()
    return [_connection_to_dict(connection) for connection in connections]


@router.post("/connections/{connection_id}/sync")
def sync_now(
    connection_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    connection = _own_connection(db, user, connection_id)
    if connection.status == "expired":
        raise HTTPException(
            status_code=409,
            detail="This bank connection has expired - reconnect to keep syncing",
        )
    summary = bank_sync.sync_connection(db, connection)
    result = summary.as_dict()
    result["connection"] = _connection_to_dict(connection)
    return result


@router.put("/accounts/{account_id}")
def toggle_account(
    account_id: int,
    enabled: bool,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = (
        db.query(BankAccount)
        .filter(BankAccount.id == account_id, BankAccount.user_id == user.id)
        .first()
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    account.enabled = enabled
    db.commit()
    return {"id": account.id, "enabled": account.enabled}


@router.delete("/connections/{connection_id}")
def disconnect(
    connection_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Drops the link and everything that only existed to serve it.

    Expenses that were already imported stay: they are the user's spending
    history, not a cache of the bank's. The BankTransaction rows go, so a
    later reconnection re-imports cleanly rather than deduping against a
    bank the user has unlinked.
    """
    connection = _own_connection(db, user, connection_id)
    account_ids = [account.id for account in connection.accounts]
    if account_ids:
        db.query(BankTransaction).filter(
            BankTransaction.user_id == user.id,
            BankTransaction.account_id.in_(account_ids),
        ).delete(synchronize_session=False)
    db.delete(connection)
    db.commit()
    return {"status": "disconnected"}


def _transaction_to_dict(row: BankTransaction, suggestion: Optional[BudgetCategory] = None) -> dict:
    return {
        "id": row.id,
        "amount": row.amount,
        "currency": row.currency,
        "merchant": row.merchant or row.description or "Unknown",
        "description": row.description,
        "date": row.booked_at.strftime("%Y-%m-%d"),
        "suggested_category_id": suggestion.id if suggestion else None,
        "suggested_category_name": suggestion.name if suggestion else None,
    }


@router.get("/inbox")
def list_inbox(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Transactions the sync would not file on its own, newest first.

    Each one carries a suggestion when the categorizer has a weak guess, so
    the common case is one tap rather than picking from the whole list.
    """
    rows = (
        db.query(BankTransaction)
        .filter(BankTransaction.user_id == user.id, BankTransaction.status == "pending")
        .order_by(BankTransaction.booked_at.desc(), BankTransaction.id.desc())
        .all()
    )
    if not rows:
        return []

    categories = db.query(BudgetCategory).filter(BudgetCategory.user_id == user.id).all()
    by_name = {category.name: category for category in categories}
    names = list(by_name)
    rules = bank_sync.rules_for(db, user)

    out = []
    for row in rows:
        suggested = suggest_category(
            merchant_key=row.merchant_key or "",
            mcc=row.mcc,
            category_names=names,
            rules=rules,
        )
        out.append(_transaction_to_dict(row, by_name.get(suggested) if suggested else None))
    return out


@router.post("/inbox/{transaction_id}")
def file_transaction(
    transaction_id: int,
    payload: FileTransactionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Files one pending transaction as an expense, and learns the merchant.

    The learned rule is what makes this feature get quieter: after the first
    Lidl run, every later one lands in the budget without being asked about.
    """
    row = (
        db.query(BankTransaction)
        .filter(BankTransaction.id == transaction_id, BankTransaction.user_id == user.id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if row.status == "imported":
        raise HTTPException(status_code=409, detail="This transaction is already in the budget")

    category = (
        db.query(BudgetCategory)
        .filter(BudgetCategory.id == payload.category_id, BudgetCategory.user_id == user.id)
        .first()
    )
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")

    converted = bank_sync.convert_for_user(row.amount, row.currency, user)
    if converted is None:
        raise HTTPException(
            status_code=503,
            detail="Exchange rates are unavailable right now - try again shortly",
        )
    amount, original_amount, original_currency, fx_rate = converted

    expense = Expense(
        user_id=user.id,
        amount=amount,
        original_amount=original_amount,
        original_currency=original_currency,
        fx_rate=fx_rate,
        category=category.name,
        category_id=category.id,
        raw_message=row.merchant or row.description or category.name,
        created_at=row.booked_at,
        source=bank_sync.EXPENSE_SOURCE,
    )
    db.add(expense)
    db.flush()

    row.status = "imported"
    row.expense_id = expense.id

    if payload.remember and row.merchant_key:
        existing = (
            db.query(MerchantRule)
            .filter(MerchantRule.user_id == user.id, MerchantRule.pattern == row.merchant_key)
            .first()
        )
        if existing is None:
            db.add(MerchantRule(user_id=user.id, pattern=row.merchant_key, category_id=category.id))
        else:
            existing.category_id = category.id

    db.commit()
    return {
        "status": "imported",
        "expense_id": expense.id,
        "remembered": bool(payload.remember and row.merchant_key),
    }


@router.delete("/inbox/{transaction_id}")
def ignore_transaction(
    transaction_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(BankTransaction)
        .filter(BankTransaction.id == transaction_id, BankTransaction.user_id == user.id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    row.status = "ignored"
    db.commit()
    return {"status": "ignored"}


@router.get("/rules")
def list_rules(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (
        db.query(MerchantRule, BudgetCategory)
        .join(BudgetCategory, MerchantRule.category_id == BudgetCategory.id)
        .filter(MerchantRule.user_id == user.id)
        .order_by(MerchantRule.pattern)
        .all()
    )
    return [
        {
            "id": rule.id,
            "pattern": rule.pattern,
            "category_id": category.id,
            "category_name": category.name,
            "category_icon": category.icon,
        }
        for rule, category in rows
    ]


@router.delete("/rules/{rule_id}")
def delete_rule(
    rule_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rule = (
        db.query(MerchantRule)
        .filter(MerchantRule.id == rule_id, MerchantRule.user_id == user.id)
        .first()
    )
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    return {"status": "deleted"}
