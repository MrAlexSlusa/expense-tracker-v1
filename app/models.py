from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class User(Base):
    """
    An app account: email plus either a password or a social provider.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=True, index=True)
    hashed_password = Column(String, nullable=True)
    currency = Column(String, nullable=False, default="USD")
    # IANA name, e.g. "Europe/Bucharest". Null means never set, treated as UTC.
    # Expenses are always stored in UTC; this is only ever used to decide which
    # calendar day a stored instant falls on for the person reading it.
    timezone = Column(String, nullable=True)
    onboarded = Column(Boolean, nullable=False, default=False)  # false only on accounts left half-set-up by the signup quiz this replaced
    created_at = Column(DateTime, default=datetime.utcnow)

    # Set when the account was created (or last signed in) through Google /
    # Apple / GitHub. Identity is still keyed on email - these are for showing
    # the user how they got in, and for telling a passwordless social account
    # apart from one whose password was simply never set.
    oauth_provider = Column(String, nullable=True)
    oauth_sub = Column(String, nullable=True)  # the provider's own stable user id

    display_name = Column(String, nullable=True)
    avatar_url = Column(String, nullable=True)  # data URL (small, base64-encoded image) or an /uploads path

    # Target split for the GOALS section of the budget view; must sum to 100.

    expenses = relationship("Expense", back_populates="user")
    categories = relationship("BudgetCategory", back_populates="user")


class OtpCode(Base):
    """
    A short-lived, single-use code emailed to the user - for either logging
    in or resetting a forgotten password. Both
    purposes share this table since the shape (a code that expires and gets
    used once) is identical; `purpose` keeps them from being interchangeable.
    """
    __tablename__ = "otp_codes"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    code_hash = Column(String, nullable=False)
    purpose = Column(String, nullable=False)  # "login" or "reset"
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class BudgetCategory(Base):
    """
    The app's own copy of the spreadsheet mechanic: a fixed set of category
    rows per user (name + optional monthly target). Unlike the old design,
    this table holds no running total - totals are always computed from
    Expense rows for whatever month is being viewed (see get_budget in
    api.py), so a month is just a date filter rather than its own set of
    duplicated category rows, and renaming/retargeting a category doesn't
    require touching historical numbers.
    """
    __tablename__ = "budget_categories"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    target = Column(Float, nullable=True)  # monthly target; None = no limit set
    icon = Column(String, nullable=False, default="\U0001F4B0")  # emoji shown in the UI
    tag = Column(String, nullable=True)  # "Needs" / "Wants" / "Savings", or None if unset

    user = relationship("User", back_populates="categories")
    expenses = relationship("Expense", back_populates="matched_category")




class Expense(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Float, nullable=False)
    category = Column(String, nullable=True)  # raw category text the parser extracted, if any
    category_id = Column(Integer, ForeignKey("budget_categories.id"), nullable=True)  # matched row, for monthly totals
    raw_message = Column(String, nullable=False)  # always keep the original text for debugging/trust
    created_at = Column(DateTime, default=datetime.utcnow)
    source = Column(String, nullable=True)  # "import" for spreadsheet-imported rows, None otherwise

    # An expense paid in a currency other than the user's default keeps
    # both numbers. `amount` above is ALWAYS in the user's currency - every
    # total, target and chart sums that column, so a mixed-currency ledger
    # would otherwise add lei to euros. These three record what was actually
    # spent, so the row can be shown as "€25 (131.31 lei)" and so a past
    # conversion stays explainable after the rate has moved.
    #
    # All null for a same-currency expense, which is most of them.
    original_amount = Column(Float, nullable=True)
    original_currency = Column(String, nullable=True)
    fx_rate = Column(Float, nullable=True)  # user-currency units per one original unit, at time of entry

    user = relationship("User", back_populates="expenses")
    matched_category = relationship("BudgetCategory", back_populates="expenses")


class BankConnection(Base):
    """
    One linked bank, via an open-banking aggregator (currently GoCardless
    Bank Account Data, which is what reaches a personal Revolut account -
    Revolut's own API is Business-only).

    The aggregator owns the consent: we keep its requisition id so we can
    re-read the account list, and consent_expires_at so the app can warn
    before the 90-day PSD2 window runs out instead of just going quiet.
    """
    __tablename__ = "bank_connections"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String, nullable=False, default="gocardless")
    institution_id = Column(String, nullable=False)  # e.g. "REVOLUT_REVOLT21"
    institution_name = Column(String, nullable=True)
    requisition_id = Column(String, nullable=False, index=True)
    agreement_id = Column(String, nullable=True)
    # Our own opaque handle, echoed back by the bank on the redirect. That
    # redirect is a bare browser hit with no Authorization header, so this
    # is the only thing tying it to a user - which is why it is random
    # rather than the row id.
    reference = Column(String, nullable=True, index=True)
    # Where in the frontend to drop the user once the consent is finished.
    redirect_uri = Column(String, nullable=True)
    # "pending" until the user comes back from the bank, then "linked";
    # "expired" once the consent window has closed, "error" if a sync failed.
    status = Column(String, nullable=False, default="pending")
    consent_expires_at = Column(DateTime, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    last_error = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    accounts = relationship("BankAccount", back_populates="connection", cascade="all, delete-orphan")


class BankAccount(Base):
    """
    One account behind a connection. Revolut exposes a separate account per
    currency pocket, so a single link usually yields several of these -
    `enabled` lets the user sync only the ones they actually spend from.
    """
    __tablename__ = "bank_accounts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    connection_id = Column(Integer, ForeignKey("bank_connections.id"), nullable=False)
    external_id = Column(String, nullable=False, index=True)  # the aggregator's account uuid
    name = Column(String, nullable=True)
    iban = Column(String, nullable=True)
    currency = Column(String, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    connection = relationship("BankConnection", back_populates="accounts")


class MerchantRule(Base):
    """
    "Anything from this merchant goes in this category" - written the first
    time the user files a transaction from an unrecognised merchant, and
    consulted on every sync afterwards. This is what makes the import get
    quieter over time instead of asking forever.

    `pattern` is the normalised merchant key (see app/categorizer.py), not
    the raw bank description, so "LIDL 0123 BUCURESTI" and "Lidl Sibiu" hit
    the same rule.
    """
    __tablename__ = "merchant_rules"
    # One category per merchant per user - filing the same merchant again
    # updates the existing rule rather than stacking a second, ambiguous one.
    __table_args__ = (UniqueConstraint("user_id", "pattern", name="uq_merchant_rule_per_user"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    pattern = Column(String, nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("budget_categories.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class BankTransaction(Base):
    """
    A transaction as the bank reported it, kept whether or not it became an
    Expense.

    Two reasons it isn't collapsed straight into Expense: dedupe (a sync is
    re-run freely, and `external_id` is what makes that idempotent), and the
    confirm-inbox - a transaction whose merchant matches no rule waits here
    as "pending" rather than guessing a category.
    """
    __tablename__ = "bank_transactions"
    # What makes a re-run of a sync idempotent: the same bank transaction
    # can be offered by the API any number of times and only lands once.
    __table_args__ = (UniqueConstraint("user_id", "external_id", name="uq_bank_tx_per_user"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=False)
    external_id = Column(String, nullable=False, index=True)  # bank's transactionId, or a hash when it omits one
    booked_at = Column(DateTime, nullable=False)
    amount = Column(Float, nullable=False)  # positive = money spent, in `currency`
    currency = Column(String, nullable=False)
    merchant = Column(String, nullable=True)  # cleaned-up display name
    description = Column(String, nullable=True)  # the raw bank text, kept for trust/debugging
    merchant_key = Column(String, nullable=True, index=True)  # normalised, what rules match on
    mcc = Column(String, nullable=True)
    # "imported" (an Expense exists), "pending" (waiting in the inbox),
    # "ignored" (user dismissed it), "skipped" (income/transfer, never an expense).
    status = Column(String, nullable=False, default="pending")
    expense_id = Column(Integer, ForeignKey("expenses.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
