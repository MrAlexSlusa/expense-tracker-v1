"""
Pulls transactions off a linked bank and turns them into Expense rows.

This is the part that runs unattended - from the user pressing "sync", and
from scripts/sync_banks.py on a schedule - so every decision here leans
towards leaving a transaction alone rather than filing it wrong:

- Only money going *out* becomes an expense. Incoming amounts, top-ups,
  vault moves and refunds are recorded as "skipped" so they never show up
  again, but never touch a budget total.
- A transaction whose merchant matches no rule and no built-in hint lands as
  "pending" in the confirm inbox. Filing it there writes the rule, and the
  next one from that merchant is automatic.
- `external_id` makes a re-run idempotent, so a sync can be retried after
  any failure without duplicating what already landed. The one exception is
  a bank that sends no transaction id at all, where a fingerprint of the
  purchase stands in (see categorizer.transaction_fingerprint).
- A conversion failure (BNR rates unreachable) leaves the transaction
  pending rather than guessing a rate. Filing 25 EUR as 25 RON would
  corrupt every total that touches it, and a pending row costs one click.

Overlap window: each sync re-reads a few days before the last one. Banks
book card payments a day or two after they happen, so a sync that started
exactly where the last one ended would miss anything that settled late -
the dedupe makes re-reading free.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app import bnr, gocardless
from app.categorizer import (
    display_merchant,
    looks_like_transfer,
    normalize_merchant,
    suggest_category,
    transaction_fingerprint,
)
from app.models import (
    BankAccount,
    BankConnection,
    BankTransaction,
    BudgetCategory,
    Expense,
    MerchantRule,
    User,
)

# Days of history to ask for on the very first sync of a connection. The
# PSD2 agreement caps this at 90 anyway.
INITIAL_HISTORY_DAYS = 90

# How far before `last_synced_at` to re-read, for late-booking transactions.
OVERLAP_DAYS = 5

EXPENSE_SOURCE = "bank"


@dataclass
class SyncSummary:
    imported: int = 0  # became an Expense straight away
    pending: int = 0  # waiting in the confirm inbox
    skipped: int = 0  # income, transfers, top-ups
    duplicates: int = 0  # already seen on an earlier sync
    errors: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "imported": self.imported,
            "pending": self.pending,
            "skipped": self.skipped,
            "duplicates": self.duplicates,
            "errors": self.errors,
        }


def _parse_booking_date(transaction: dict) -> datetime:
    """
    The day the bank says the money moved, at midday.

    Midday rather than midnight because expenses are stored in UTC and read
    back in the user's zone: a 00:00 UTC stamp reads as the previous day in
    the Americas and the right day in Bucharest, while midday is the same
    calendar day either side.
    """
    raw = transaction.get("bookingDate") or transaction.get("valueDate")
    if raw:
        try:
            return datetime.strptime(str(raw)[:10], "%Y-%m-%d").replace(hour=12)
        except ValueError:
            pass
    return datetime.utcnow()


def _merchant_text(transaction: dict) -> str:
    """
    The best merchant-ish string the payload offers.

    Revolut (through GoCardless) usually puts the merchant in
    remittanceInformationUnstructured and leaves creditorName empty, while
    other banks do the opposite, so this takes whichever is populated rather
    than assuming either.
    """
    for key in ("remittanceInformationUnstructured", "creditorName", "debtorName"):
        value = transaction.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    structured = transaction.get("remittanceInformationStructured")
    if isinstance(structured, str) and structured.strip():
        return structured.strip()

    lines = transaction.get("remittanceInformationUnstructuredArray")
    if isinstance(lines, list):
        joined = " ".join(str(line) for line in lines if line)
        if joined.strip():
            return joined.strip()

    return ""


def _amount(transaction: dict) -> Optional[tuple]:
    """(signed amount, currency) as floats, or None if the payload is unusable."""
    block = transaction.get("transactionAmount") or {}
    raw = block.get("amount")
    currency = (block.get("currency") or "").strip().upper()
    if raw is None or not currency:
        return None
    try:
        return float(raw), currency
    except (TypeError, ValueError):
        return None


def _external_id(transaction: dict) -> str:
    for key in ("transactionId", "internalTransactionId", "entryReference"):
        value = transaction.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return transaction_fingerprint(transaction)


def convert_for_user(amount: float, currency: str, user: User) -> Optional[tuple]:
    """
    (amount in the user's currency, original amount, original currency, rate).

    Returns None when rates are unavailable, which the caller turns into a
    pending transaction rather than a wrong number.
    """
    own = (user.currency or "RON").strip().upper()
    if currency == own:
        return amount, None, None, None
    try:
        converted, rate = bnr.convert(amount, currency, own)
    except (bnr.RatesUnavailable, KeyError):
        return None
    return converted, amount, currency, rate


def rules_for(db: Session, user: User) -> dict:
    """Learned merchant key -> category name, for the categorizer."""
    rows = (
        db.query(MerchantRule, BudgetCategory)
        .join(BudgetCategory, MerchantRule.category_id == BudgetCategory.id)
        .filter(MerchantRule.user_id == user.id)
        .all()
    )
    return {rule.pattern: category.name for rule, category in rows}


def _date_from(connection: BankConnection) -> str:
    if connection.last_synced_at:
        start = connection.last_synced_at - timedelta(days=OVERLAP_DAYS)
    else:
        start = datetime.utcnow() - timedelta(days=INITIAL_HISTORY_DAYS)
    floor = datetime.utcnow() - timedelta(days=gocardless.MAX_HISTORICAL_DAYS)
    return max(start, floor).strftime("%Y-%m-%d")


def refresh_accounts(db: Session, connection: BankConnection) -> list:
    """
    Reads the account list behind a finished consent and stores it.

    Called when the user comes back from the bank, and again before a sync
    if the list is empty - a consent that was still unfinished at callback
    time (some banks redirect before they have provisioned the accounts)
    would otherwise stay permanently empty.
    """
    remote = gocardless.fetch_accounts(connection.requisition_id)
    existing = {account.external_id: account for account in connection.accounts}

    for item in remote:
        account = existing.get(item.external_id)
        if account is None:
            account = BankAccount(
                user_id=connection.user_id,
                connection_id=connection.id,
                external_id=item.external_id,
            )
            db.add(account)
        account.name = item.name or account.name
        account.iban = item.iban or account.iban
        account.currency = item.currency or account.currency

    if remote:
        connection.status = "linked"
        connection.last_error = None
    db.commit()
    return list(connection.accounts)


def sync_connection(db: Session, connection: BankConnection) -> SyncSummary:
    """
    Pulls every enabled account on one connection and files what it finds.

    Failures are recorded on the connection and returned in the summary
    rather than raised: a scheduled run across several users must not stop
    at the first dead consent.
    """
    summary = SyncSummary()
    user = db.query(User).filter(User.id == connection.user_id).first()
    if user is None:
        summary.errors.append("The account behind this connection no longer exists")
        return summary

    if not connection.accounts:
        try:
            refresh_accounts(db, connection)
        except gocardless.ConsentExpired as exc:
            connection.status = "expired"
            connection.last_error = str(exc)
            db.commit()
            summary.errors.append(str(exc))
            return summary
        except gocardless.BankApiError as exc:
            connection.last_error = str(exc)
            db.commit()
            summary.errors.append(str(exc))
            return summary

    categories = db.query(BudgetCategory).filter(BudgetCategory.user_id == user.id).all()
    category_names = [category.name for category in categories]
    by_name = {category.name: category for category in categories}
    rules = rules_for(db, user)
    date_from = _date_from(connection)

    started_at = datetime.utcnow()
    any_account_succeeded = False

    for account in connection.accounts:
        if not account.enabled:
            continue
        try:
            transactions = gocardless.fetch_transactions(account.external_id, date_from=date_from)
        except gocardless.ConsentExpired as exc:
            connection.status = "expired"
            connection.last_error = str(exc)
            db.commit()
            summary.errors.append(str(exc))
            return summary
        except gocardless.BankApiError as exc:
            summary.errors.append("{}: {}".format(account.name or account.external_id, exc))
            continue

        any_account_succeeded = True
        for transaction in transactions:
            _ingest(
                db,
                user=user,
                account=account,
                transaction=transaction,
                category_names=category_names,
                by_name=by_name,
                rules=rules,
                summary=summary,
            )

    if any_account_succeeded:
        connection.last_synced_at = started_at
        if not summary.errors:
            connection.last_error = None
        if connection.status != "expired":
            connection.status = "linked"
    elif summary.errors:
        connection.status = "error"
        connection.last_error = summary.errors[0]

    db.commit()
    return summary


def _ingest(
    db: Session,
    *,
    user: User,
    account: BankAccount,
    transaction: dict,
    category_names: list,
    by_name: dict,
    rules: dict,
    summary: SyncSummary,
) -> None:
    external_id = _external_id(transaction)

    seen = (
        db.query(BankTransaction)
        .filter(BankTransaction.user_id == user.id, BankTransaction.external_id == external_id)
        .first()
    )
    if seen is not None:
        summary.duplicates += 1
        return

    parsed = _amount(transaction)
    if parsed is None:
        return
    signed, currency = parsed

    merchant_text = _merchant_text(transaction)
    merchant_key = normalize_merchant(merchant_text)
    mcc = transaction.get("merchantCategoryCode")

    row = BankTransaction(
        user_id=user.id,
        account_id=account.id,
        external_id=external_id,
        booked_at=_parse_booking_date(transaction),
        # Stored positive: everything downstream reads this as "money spent",
        # and keeping the bank's sign would mean every consumer re-deciding
        # which direction negative means.
        amount=abs(signed),
        currency=currency,
        merchant=display_merchant(merchant_text) or None,
        description=merchant_text or None,
        merchant_key=merchant_key or None,
        mcc=str(mcc) if mcc else None,
    )

    # Money in, or money moved between the user's own pockets. Recorded so it
    # stops being offered, but never a budget line.
    if signed >= 0 or looks_like_transfer(merchant_text):
        row.status = "skipped"
        db.add(row)
        db.commit()
        summary.skipped += 1
        return

    suggested = suggest_category(
        merchant_key=merchant_key,
        mcc=row.mcc,
        category_names=category_names,
        rules=rules,
    )
    category = by_name.get(suggested) if suggested else None

    converted = convert_for_user(row.amount, currency, user) if category else None
    if category is None or converted is None:
        # No confident category, or no exchange rate to convert with. Either
        # way this waits for the user instead of being guessed at.
        row.status = "pending"
        db.add(row)
        db.commit()
        summary.pending += 1
        return

    amount, original_amount, original_currency, fx_rate = converted
    expense = Expense(
        user_id=user.id,
        amount=amount,
        original_amount=original_amount,
        original_currency=original_currency,
        fx_rate=fx_rate,
        category=category.name,
        category_id=category.id,
        raw_message=row.merchant or merchant_text or category.name,
        created_at=row.booked_at,
        source=EXPENSE_SOURCE,
    )
    db.add(expense)
    db.flush()

    row.status = "imported"
    row.expense_id = expense.id
    db.add(row)
    db.commit()
    summary.imported += 1


def sync_all(db: Session) -> dict:
    """
    Every connection that is still linked. This is the scheduled entry point
    (scripts/sync_banks.py), so one user's broken consent must not keep the
    rest from syncing.
    """
    totals = SyncSummary()
    connections = (
        db.query(BankConnection)
        .filter(BankConnection.status.in_(["linked", "error"]))
        .all()
    )
    for connection in connections:
        summary = sync_connection(db, connection)
        totals.imported += summary.imported
        totals.pending += summary.pending
        totals.skipped += summary.skipped
        totals.duplicates += summary.duplicates
        totals.errors.extend(summary.errors)

    result = totals.as_dict()
    result["connections"] = len(connections)
    return result
