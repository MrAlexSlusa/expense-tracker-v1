from datetime import datetime, date, timedelta
from calendar import monthrange
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import User, Expense, BudgetCategory, IncomeSource
from app.utils import normalize_phone, best_category_match
from app.auth import hash_password, verify_password, create_access_token, get_current_user, issue_otp, consume_otp
from app.parser import parse_expense_message
from app.email_sender import send_otp_email
from app.quiz import public_questions, compute_categories, fallback_category
from app.importer import parse_workbook, guess_period_from_filename
from app.schemas import (
    SignupRequest,
    LoginRequest,
    TokenResponse,
    LoginResponse,
    VerifyOtpRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    TwoFactorUpdateRequest,
    OnboardingRequest,
    ChatMessageRequest,
    ChatMessageResponse,
    CategoryCreateRequest,
    CategoryUpdateRequest,
    CurrencyUpdateRequest,
    ExpenseCreateRequest,
    ExpenseUpdateRequest,
    ProfileUpdateRequest,
    GoalUpdateRequest,
    IncomeCreateRequest,
    IncomeUpdateRequest,
)

router = APIRouter()

MAX_AVATAR_DATA_URL_LENGTH = 700_000  # ~500KB image, base64-inflated ~1.37x, plus data-url prefix headroom


def _month_bounds(period: Optional[str]) -> tuple[datetime, datetime]:
    """
    Parses a "YYYY-MM" string (defaulting to the current month) into the
    [start, end) datetime range used to filter expenses for that month.
    """
    if period:
        try:
            year, month = (int(p) for p in period.split("-"))
        except ValueError:
            raise HTTPException(status_code=400, detail="period must be in YYYY-MM format")
    else:
        today = date.today()
        year, month = today.year, today.month

    start = datetime(year, month, 1)
    days_in_month = monthrange(year, month)[1]
    end = datetime(year, month, days_in_month, 23, 59, 59)
    return start, end


@router.get("/api/users/{phone_number}/expenses")
def list_expenses(phone_number: str, db: Session = Depends(get_db)):
    phone_number = normalize_phone(phone_number)
    user = db.query(User).filter(User.phone_number == phone_number).first()
    if user is None:
        raise HTTPException(status_code=404, detail="No expenses logged for this number yet")

    expenses = (
        db.query(Expense)
        .filter(Expense.user_id == user.id)
        .order_by(Expense.created_at.desc())
        .all()
    )
    return [
        {
            "amount": e.amount,
            "category": e.category or "uncategorized",
            "raw_message": e.raw_message,
            "created_at": e.created_at.isoformat(),
        }
        for e in expenses
    ]


@router.get("/api/users/{phone_number}/summary")
def spending_summary(phone_number: str, db: Session = Depends(get_db)):
    phone_number = normalize_phone(phone_number)
    user = db.query(User).filter(User.phone_number == phone_number).first()
    if user is None:
        raise HTTPException(status_code=404, detail="No expenses logged for this number yet")

    rows = (
        db.query(Expense.category, func.sum(Expense.amount), func.count(Expense.id))
        .filter(Expense.user_id == user.id)
        .group_by(Expense.category)
        .all()
    )
    total = sum(r[1] for r in rows)
    return {
        "total": round(total, 2),
        "by_category": [
            {"category": cat or "uncategorized", "total": round(amt, 2), "count": cnt}
            for cat, amt, cnt in rows
        ],
    }


# --- App account endpoints (email/password + JWT) -------------------------
# Separate identity path from the WhatsApp phone-number flow above; both
# land on the same User/Expense tables.


@router.post("/api/auth/signup", response_model=TokenResponse)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing is not None:
        raise HTTPException(status_code=400, detail="An account with this email already exists")

    user = User(email=payload.email, hashed_password=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)

    # A single safety-net category so the fuzzy-match fallback (best_category_match)
    # always has somewhere to land - replaced with the quiz-picked set once
    # POST /api/onboarding/complete runs (see `onboarded` below).
    name, icon = fallback_category(payload.lang)
    db.add(BudgetCategory(user_id=user.id, name=name, icon=icon))
    db.commit()

    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/api/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    invalid = HTTPException(status_code=401, detail="Incorrect email or password")
    if user is None or user.hashed_password is None:
        raise invalid
    if not verify_password(payload.password, user.hashed_password):
        raise invalid

    if user.two_factor_enabled:
        code = issue_otp(db, user, "login")
        send_otp_email(user.email, code, "login")
        return LoginResponse(requires_otp=True)

    return LoginResponse(access_token=create_access_token(user.id))


@router.post("/api/auth/verify-otp", response_model=TokenResponse)
def verify_login_otp(payload: VerifyOtpRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    invalid = HTTPException(status_code=401, detail="Incorrect or expired code")
    if user is None or not consume_otp(db, user, "login", payload.code):
        raise invalid
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/api/auth/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    # Always the same response either way, so this endpoint can't be used to
    # probe which emails have accounts.
    if user is not None and user.hashed_password is not None:
        code = issue_otp(db, user, "reset")
        send_otp_email(user.email, code, "reset")
    return {"sent": True}


@router.post("/api/auth/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    invalid = HTTPException(status_code=401, detail="Incorrect or expired code")
    if user is None or not consume_otp(db, user, "reset", payload.code):
        raise invalid

    user.hashed_password = hash_password(payload.new_password)
    db.commit()
    return {"reset": True}


@router.get("/api/me")
def get_me(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "email": user.email,
        "currency": user.currency,
        "two_factor_enabled": user.two_factor_enabled,
        "onboarded": user.onboarded,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "wants_goal_pct": user.wants_goal_pct,
        "needs_goal_pct": user.needs_goal_pct,
        "savings_goal_pct": user.savings_goal_pct,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


# --- Profile: display name, avatar, and derived spending stats -------------


@router.put("/api/me/profile")
def update_profile(
    payload: ProfileUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.display_name is not None:
        name = payload.display_name.strip()
        user.display_name = name or None
    if payload.avatar_url is not None:
        if payload.avatar_url == "":
            user.avatar_url = None
        else:
            if len(payload.avatar_url) > MAX_AVATAR_DATA_URL_LENGTH:
                raise HTTPException(status_code=400, detail="Image is too large - try a smaller picture")
            if not payload.avatar_url.startswith("data:image/"):
                raise HTTPException(status_code=400, detail="Avatar must be an image")
            user.avatar_url = payload.avatar_url

    db.commit()
    return {"display_name": user.display_name, "avatar_url": user.avatar_url}


@router.get("/api/me/stats")
def get_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    total_all_time = (
        db.query(func.sum(Expense.amount)).filter(Expense.user_id == user.id).scalar() or 0.0
    )

    start, end = _month_bounds(None)
    total_this_month = (
        db.query(func.sum(Expense.amount))
        .filter(Expense.user_id == user.id, Expense.created_at >= start, Expense.created_at <= end)
        .scalar()
        or 0.0
    )

    monthly_totals = (
        db.query(Expense.created_at, Expense.amount).filter(Expense.user_id == user.id).all()
    )
    by_month: dict[str, float] = {}
    for created_at, amount in monthly_totals:
        key = f"{created_at.year:04d}-{created_at.month:02d}"
        by_month[key] = by_month.get(key, 0.0) + amount
    monthly_average = (sum(by_month.values()) / len(by_month)) if by_month else 0.0

    top_category_row = (
        db.query(BudgetCategory.name, func.sum(Expense.amount).label("total"))
        .join(Expense, Expense.category_id == BudgetCategory.id)
        .filter(Expense.user_id == user.id)
        .group_by(BudgetCategory.name)
        .order_by(func.sum(Expense.amount).desc())
        .first()
    )

    dates_with_expenses = {
        e.created_at.date()
        for e in db.query(Expense.created_at).filter(Expense.user_id == user.id).all()
    }
    streak = 0
    cursor = date.today()
    while cursor in dates_with_expenses:
        streak += 1
        cursor -= timedelta(days=1)

    return {
        "total_all_time": round(total_all_time, 2),
        "total_this_month": round(total_this_month, 2),
        "monthly_average": round(monthly_average, 2),
        "top_category": top_category_row[0] if top_category_row else None,
        "top_category_total": round(top_category_row[1], 2) if top_category_row else None,
        "current_streak_days": streak,
        "member_since": user.created_at.isoformat() if user.created_at else None,
        "months_tracked": len(by_month),
    }


@router.put("/api/me/goals")
def update_goals(
    payload: GoalUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    total = payload.wants_pct + payload.needs_pct + payload.savings_pct
    if abs(total - 100) > 0.5:
        raise HTTPException(status_code=400, detail="Wants + Needs + Savings must add up to 100%")

    user.wants_goal_pct = payload.wants_pct
    user.needs_goal_pct = payload.needs_pct
    user.savings_goal_pct = payload.savings_pct
    db.commit()
    return {
        "wants_goal_pct": user.wants_goal_pct,
        "needs_goal_pct": user.needs_goal_pct,
        "savings_goal_pct": user.savings_goal_pct,
    }


@router.put("/api/me/two-factor")
def update_two_factor(
    payload: TwoFactorUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user.two_factor_enabled = payload.enabled
    db.commit()
    return {"two_factor_enabled": user.two_factor_enabled}


# --- Signup quiz: picks 5 starting categories instead of a generic set -----


@router.get("/api/quiz")
def get_quiz():
    return public_questions()


@router.post("/api/onboarding/complete")
def complete_onboarding(
    payload: OnboardingRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    answer_pairs = list(payload.answers.items())
    categories = compute_categories(answer_pairs, payload.lang)

    # Replaces whatever's there (normally just the signup-time Altele
    # placeholder) rather than appending, so retaking the quiz later - once
    # that's exposed in Settings - doesn't pile up duplicates.
    db.query(Expense).filter(Expense.user_id == user.id).update({"category_id": None})
    db.query(BudgetCategory).filter(BudgetCategory.user_id == user.id).delete()

    created = []
    for name, icon in categories:
        category = BudgetCategory(user_id=user.id, name=name, icon=icon)
        db.add(category)
        created.append(category)

    user.onboarded = True
    db.commit()
    for c in created:
        db.refresh(c)

    return [{"id": c.id, "name": c.name, "icon": c.icon, "target": c.target} for c in created]


@router.put("/api/me/currency")
def update_currency(
    payload: CurrencyUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    code = payload.currency.strip().upper()
    if not code or len(code) > 8:
        raise HTTPException(status_code=400, detail="Invalid currency code")
    user.currency = code
    db.commit()
    return {"currency": user.currency}


# --- In-app chat: same parser the WhatsApp webhook uses --------------------


@router.post("/api/chat/message", response_model=ChatMessageResponse)
def send_chat_message(
    payload: ChatMessageRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    parsed = parse_expense_message(payload.text)
    if parsed is None:
        return ChatMessageResponse(parsed=False)

    categories = db.query(BudgetCategory).filter(BudgetCategory.user_id == user.id).all()
    matched_name = best_category_match(parsed.category, [c.name for c in categories])
    matched = next((c for c in categories if c.name == matched_name), None)

    expense = Expense(
        user_id=user.id,
        amount=parsed.amount,
        category=parsed.category,
        category_id=matched.id if matched is not None else None,
        raw_message=payload.text,
    )
    db.add(expense)
    db.commit()

    label = matched.name if matched is not None else (parsed.category or "uncategorized")
    response = ChatMessageResponse(amount=parsed.amount, category=label)

    if matched is not None and matched.target is not None:
        start, end = _month_bounds(None)
        spent = (
            db.query(func.sum(Expense.amount))
            .filter(Expense.user_id == user.id, Expense.category_id == matched.id)
            .filter(Expense.created_at >= start, Expense.created_at <= end)
            .scalar()
            or 0.0
        )
        if spent > matched.target:
            response.over_budget = True
            response.spent = round(spent, 2)
            response.target = matched.target

    return response


# --- Budget view: the app's version of the spreadsheet ---------------------
# A "month" is just a date filter over Expense rows, not a duplicated set of
# category rows - the category list (names, targets, icons) is shared across
# every month you look at.


@router.get("/api/budget")
def get_budget(
    period: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start, end = _month_bounds(period)
    categories = db.query(BudgetCategory).filter(BudgetCategory.user_id == user.id).all()

    totals = dict(
        db.query(Expense.category_id, func.sum(Expense.amount))
        .filter(Expense.user_id == user.id, Expense.created_at >= start, Expense.created_at <= end)
        .group_by(Expense.category_id)
        .all()
    )

    return [
        {
            "id": c.id,
            "name": c.name,
            "icon": c.icon,
            "target": c.target,
            "tag": c.tag,
            "total": round(totals.get(c.id, 0.0), 2),
            "over_budget": c.target is not None and totals.get(c.id, 0.0) > c.target,
        }
        for c in categories
    ]


@router.get("/api/budget/goals")
def get_budget_goals(
    period: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    The GOALS/ACTUAL block from the spreadsheet: target % (from the user's
    profile) vs actual % for Wants/Needs/Savings. Matches the spreadsheet's
    own math - each tag's spend as a share of that period's TOTAL INCOME
    (not of total spend; confirmed against the real sheets, e.g. Jan 2026:
    2.282,43 Wants spend / 3.365,00 total income = 67,83%, the exact figure
    in that sheet's ACTUAL row) - so overspending relative to income shows
    up the same way it does there, including going over 100%.
    """
    start, end = _month_bounds(period)
    rows = (
        db.query(BudgetCategory.tag, func.sum(Expense.amount))
        .join(Expense, Expense.category_id == BudgetCategory.id)
        .filter(Expense.user_id == user.id, Expense.created_at >= start, Expense.created_at <= end)
        .group_by(BudgetCategory.tag)
        .all()
    )
    by_tag = {tag: amount for tag, amount in rows if tag}

    total_income = (
        db.query(func.sum(IncomeSource.amount))
        .filter(IncomeSource.user_id == user.id, IncomeSource.period == (period or _current_period()))
        .scalar()
        or 0.0
    )

    targets = {"Wants": user.wants_goal_pct, "Needs": user.needs_goal_pct, "Savings": user.savings_goal_pct}
    return [
        {
            "tag": tag,
            "target_pct": targets[tag],
            "actual_pct": round((by_tag.get(tag, 0.0) / total_income) * 100, 2) if total_income else 0.0,
            "actual_amount": round(by_tag.get(tag, 0.0), 2),
        }
        for tag in ("Wants", "Needs", "Savings")
    ]


@router.get("/api/budget/periods")
def list_budget_periods(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Every "YYYY-MM" that has at least one logged expense, newest first, for
    the month-picker menu - plus the current month even if it's still empty.
    """
    rows = (
        db.query(Expense.created_at)
        .filter(Expense.user_id == user.id)
        .all()
    )
    periods = {f"{d.year:04d}-{d.month:02d}" for (d,) in rows}
    current = date.today()
    periods.add(f"{current.year:04d}-{current.month:02d}")
    return sorted(periods, reverse=True)


@router.get("/api/budget/graph")
def get_yearly_graph(
    year: Optional[int] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Total spend per month for one year - the data behind the Graph tab."""
    year = year or date.today().year
    start = datetime(year, 1, 1)
    end = datetime(year, 12, 31, 23, 59, 59)

    rows = (
        db.query(Expense.created_at, Expense.amount)
        .filter(Expense.user_id == user.id, Expense.created_at >= start, Expense.created_at <= end)
        .all()
    )
    monthly = [0.0] * 12
    for created_at, amount in rows:
        monthly[created_at.month - 1] += amount

    return {"year": year, "months": [round(m, 2) for m in monthly]}


@router.post("/api/budget/categories")
def create_category(
    payload: CategoryCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Category name can't be empty")

    category = BudgetCategory(
        user_id=user.id,
        name=name,
        target=payload.target,
        icon=payload.icon or "\U0001F4B0",
        tag=payload.tag,
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    return {"id": category.id, "name": category.name, "icon": category.icon, "target": category.target, "tag": category.tag}


@router.put("/api/budget/categories/{category_id}")
def update_category(
    category_id: int,
    payload: CategoryUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    category = (
        db.query(BudgetCategory)
        .filter(BudgetCategory.id == category_id, BudgetCategory.user_id == user.id)
        .first()
    )
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Category name can't be empty")
        category.name = name
    if payload.icon is not None:
        category.icon = payload.icon
    if payload.clear_target:
        category.target = None
    elif payload.target is not None:
        category.target = payload.target
    if payload.clear_tag:
        category.tag = None
    elif payload.tag is not None:
        category.tag = payload.tag

    db.commit()
    return {"id": category.id, "name": category.name, "icon": category.icon, "target": category.target, "tag": category.tag}


@router.delete("/api/budget/categories/{category_id}")
def delete_category(
    category_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    category = (
        db.query(BudgetCategory)
        .filter(BudgetCategory.id == category_id, BudgetCategory.user_id == user.id)
        .first()
    )
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")

    # Expenses already filed under this category keep their history (raw
    # parsed text survives in Expense.category) but stop counting toward
    # any budget total once the row itself is gone.
    db.query(Expense).filter(Expense.category_id == category.id).update({"category_id": None})
    db.delete(category)
    db.commit()
    return {"deleted": True}


# --- Expense ledger ----------------------------------------------------
# The budget totals above are read-only aggregates. These endpoints let you
# see, add, edit, and delete the individual entries behind them - for any
# month, not just the current one - which is what actually makes a past
# month's "spreadsheet" editable rather than just a frozen summary.


def _parse_date_or_400(date_str: Optional[str]) -> datetime:
    if not date_str:
        return datetime.utcnow()
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(hour=12)
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be in YYYY-MM-DD format")


def _expense_to_dict(e: Expense) -> dict:
    return {
        "id": e.id,
        "amount": e.amount,
        "category_id": e.category_id,
        "category_name": e.matched_category.name if e.matched_category else None,
        "category_icon": e.matched_category.icon if e.matched_category else None,
        "note": e.raw_message,
        "date": e.created_at.strftime("%Y-%m-%d"),
    }


@router.get("/api/expenses")
def list_expenses_for_period(
    period: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start, end = _month_bounds(period)
    expenses = (
        db.query(Expense)
        .filter(Expense.user_id == user.id, Expense.created_at >= start, Expense.created_at <= end)
        .order_by(Expense.created_at.desc())
        .all()
    )
    return [_expense_to_dict(e) for e in expenses]


@router.post("/api/expenses")
def create_expense(
    payload: ExpenseCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    category = None
    if payload.category_id is not None:
        category = (
            db.query(BudgetCategory)
            .filter(BudgetCategory.id == payload.category_id, BudgetCategory.user_id == user.id)
            .first()
        )
        if category is None:
            raise HTTPException(status_code=404, detail="Category not found")

    expense = Expense(
        user_id=user.id,
        amount=payload.amount,
        category=category.name if category else None,
        category_id=category.id if category else None,
        raw_message=payload.note or (category.name if category else "Manual entry"),
        created_at=_parse_date_or_400(payload.date),
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return _expense_to_dict(expense)


@router.put("/api/expenses/{expense_id}")
def update_expense(
    expense_id: int,
    payload: ExpenseUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    expense = db.query(Expense).filter(Expense.id == expense_id, Expense.user_id == user.id).first()
    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found")

    if payload.amount is not None:
        expense.amount = payload.amount
    if payload.clear_category:
        expense.category_id = None
    elif payload.category_id is not None:
        category = (
            db.query(BudgetCategory)
            .filter(BudgetCategory.id == payload.category_id, BudgetCategory.user_id == user.id)
            .first()
        )
        if category is None:
            raise HTTPException(status_code=404, detail="Category not found")
        expense.category_id = category.id
        expense.category = category.name
    if payload.date is not None:
        expense.created_at = _parse_date_or_400(payload.date)
    if payload.note is not None:
        expense.raw_message = payload.note

    db.commit()
    db.refresh(expense)
    return _expense_to_dict(expense)


@router.delete("/api/expenses/{expense_id}")
def delete_expense(
    expense_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    expense = db.query(Expense).filter(Expense.id == expense_id, Expense.user_id == user.id).first()
    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    db.delete(expense)
    db.commit()
    return {"deleted": True}


# --- Income sources ----------------------------------------------------
# The INCOME column of the spreadsheet: named amounts for one month, no
# category matching needed since it's income rather than spend.


def _income_to_dict(i: IncomeSource) -> dict:
    return {"id": i.id, "name": i.name, "amount": i.amount, "period": i.period}


@router.get("/api/income")
def list_income(
    period: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    period = period or _current_period()
    rows = (
        db.query(IncomeSource)
        .filter(IncomeSource.user_id == user.id, IncomeSource.period == period)
        .order_by(IncomeSource.id)
        .all()
    )
    return [_income_to_dict(i) for i in rows]


@router.post("/api/income")
def create_income(
    payload: IncomeCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Income name can't be empty")

    income = IncomeSource(
        user_id=user.id,
        name=name,
        amount=payload.amount,
        period=payload.period or _current_period(),
    )
    db.add(income)
    db.commit()
    db.refresh(income)
    return _income_to_dict(income)


@router.put("/api/income/{income_id}")
def update_income(
    income_id: int,
    payload: IncomeUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    income = db.query(IncomeSource).filter(IncomeSource.id == income_id, IncomeSource.user_id == user.id).first()
    if income is None:
        raise HTTPException(status_code=404, detail="Income source not found")

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Income name can't be empty")
        income.name = name
    if payload.amount is not None:
        income.amount = payload.amount

    db.commit()
    return _income_to_dict(income)


@router.delete("/api/income/{income_id}")
def delete_income(
    income_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    income = db.query(IncomeSource).filter(IncomeSource.id == income_id, IncomeSource.user_id == user.id).first()
    if income is None:
        raise HTTPException(status_code=404, detail="Income source not found")
    db.delete(income)
    db.commit()
    return {"deleted": True}


def _current_period() -> str:
    today = date.today()
    return f"{today.year:04d}-{today.month:02d}"


# --- Spreadsheet import --------------------------------------------------
# Uploads the same shape of file as the user's own Google Sheets budget
# ("<Month> Budget Tracker") and populates categories/expenses/income/goals
# from it. See app/importer.py for the parsing rules.


@router.post("/api/import/spreadsheet")
async def import_spreadsheet(
    file: UploadFile = File(...),
    period: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    content = await file.read()
    period = period or guess_period_from_filename(file.filename or "") or _current_period()

    try:
        result = parse_workbook(content, file.filename or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not result.income and not result.categories:
        raise HTTPException(status_code=400, detail="Couldn't find any income or spending rows in this file")

    existing_categories = {c.name.lower(): c for c in db.query(BudgetCategory).filter(BudgetCategory.user_id == user.id).all()}
    categories_created = 0
    categories_updated = 0

    # Re-importing the same period replaces that period's prior import, so
    # running the same file twice doesn't double the totals.
    period_start, period_end = _month_bounds(period)
    db.query(Expense).filter(
        Expense.user_id == user.id,
        Expense.source == "import",
        Expense.created_at >= period_start,
        Expense.created_at <= period_end,
    ).delete(synchronize_session=False)
    db.query(IncomeSource).filter(IncomeSource.user_id == user.id, IncomeSource.period == period).delete(
        synchronize_session=False
    )

    import_date = period_start.replace(hour=12)

    for row in result.categories:
        category = existing_categories.get(row.name.lower())
        if category is None:
            category = BudgetCategory(user_id=user.id, name=row.name, tag=row.tag)
            db.add(category)
            db.flush()
            existing_categories[row.name.lower()] = category
            categories_created += 1
        else:
            if row.tag and category.tag != row.tag:
                category.tag = row.tag
            categories_updated += 1

        db.add(
            Expense(
                user_id=user.id,
                amount=row.amount,
                category=category.name,
                category_id=category.id,
                raw_message=f"Imported from spreadsheet ({file.filename})",
                created_at=import_date,
                source="import",
            )
        )

    for row in result.income:
        db.add(IncomeSource(user_id=user.id, name=row.name, amount=row.amount, period=period))

    for tag, goal in result.goals.items():
        if goal.target_pct is None:
            continue
        if tag == "Wants":
            user.wants_goal_pct = goal.target_pct
        elif tag == "Needs":
            user.needs_goal_pct = goal.target_pct
        elif tag == "Savings":
            user.savings_goal_pct = goal.target_pct

    db.commit()

    return {
        "period": period,
        "categories_created": categories_created,
        "categories_updated": categories_updated,
        "income_rows": len(result.income),
        "total_imported": round(sum(r.amount for r in result.categories), 2),
        "warnings": result.warnings,
    }
