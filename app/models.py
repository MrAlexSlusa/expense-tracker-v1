from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class User(Base):
    """
    A user can come from either channel: a WhatsApp number (no signup form
    needed) or an app account (email + password). Both columns are nullable
    since a given user may only ever use one of the two.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    phone_number = Column(String, unique=True, nullable=True, index=True)
    email = Column(String, unique=True, nullable=True, index=True)
    hashed_password = Column(String, nullable=True)
    currency = Column(String, nullable=False, default="USD")
    two_factor_enabled = Column(Boolean, nullable=False, default=False)
    onboarded = Column(Boolean, nullable=False, default=False)  # false until the signup quiz picks their categories
    created_at = Column(DateTime, default=datetime.utcnow)

    display_name = Column(String, nullable=True)
    avatar_url = Column(String, nullable=True)  # data URL (small, base64-encoded image) or an /uploads path

    # Target split for the GOALS section of the budget view; must sum to 100.
    wants_goal_pct = Column(Float, nullable=False, default=50.0)
    needs_goal_pct = Column(Float, nullable=False, default=40.0)
    savings_goal_pct = Column(Float, nullable=False, default=10.0)

    expenses = relationship("Expense", back_populates="user")
    categories = relationship("BudgetCategory", back_populates="user")
    income_sources = relationship("IncomeSource", back_populates="user")
    accounts = relationship("Account", back_populates="user")


class OtpCode(Base):
    """
    A short-lived, single-use code emailed to the user - for either logging
    in (when two_factor_enabled) or resetting a forgotten password. Both
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


class IncomeSource(Base):
    """
    A named income line for one month (e.g. "ING ramas", "Bursa") - the
    INCOME column of the user's spreadsheet. Kept separate from Expense
    since it's income, not spend, and doesn't need category matching.
    """
    __tablename__ = "income_sources"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    period = Column(String, nullable=False, index=True)  # "YYYY-MM"
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="income_sources")


class Account(Base):
    """
    A place money is spent from - a bank account, a card, or cash. Purely
    descriptive: the balance is a number the user maintains, not something
    derived from Expense rows, because most of what lands in an account
    (salary, transfers) never passes through this app. Expenses point at one
    optionally, so a transaction can say where it came from without
    accounts being mandatory for the WhatsApp flow.
    """
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    kind = Column(String, nullable=True)  # "Current" / "Debit" / "Wallet" - free text, shown as the row subtitle
    last4 = Column(String, nullable=True)  # last digits of the card/account, if it has any
    balance = Column(Float, nullable=False, default=0.0)
    icon = Column(String, nullable=False, default="🏦")  # emoji shown in the UI
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="accounts")
    expenses = relationship("Expense", back_populates="account")


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
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)  # which account it was paid from, if known

    user = relationship("User", back_populates="expenses")
    matched_category = relationship("BudgetCategory", back_populates="expenses")
    account = relationship("Account", back_populates="expenses")
