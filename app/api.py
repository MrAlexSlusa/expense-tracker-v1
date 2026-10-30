from datetime import datetime, date, time, timezone as dt_timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from calendar import monthrange
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import User, Expense, BudgetCategory, OtpCode
from app.auth import hash_password, verify_password, create_access_token, get_current_user, issue_otp, consume_otp
from app.email_sender import send_otp_email
from app.starter import FALLBACK_NAMES, starter_categories
from app import oauth
from app.importer import parse_workbook, guess_period_from_filename
from app import bnr
from app.schemas import (
    SignupRequest,
    LoginRequest,
    TokenResponse,
    LoginResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    DeleteAccountRequest,
    CategoryCreateRequest,
    CategoryUpdateRequest,
    CurrencyUpdateRequest,
    TimezoneUpdateRequest,
    ExpenseCreateRequest,
    ExpenseUpdateRequest,
    ProfileUpdateRequest,
)

router = APIRouter()

MAX_AVATAR_DATA_URL_LENGTH = 700_000  # ~500KB image, base64-inflated ~1.37x, plus data-url prefix headroom


UTC = dt_timezone.utc


def user_zone(user: Optional[User]) -> object:
    """
    The user's timezone, or UTC when it is unset or no longer a real IANA name.

    Falling back rather than raising is deliberate: a stale or mistyped zone
    should make dates slightly wrong, not make the whole app return 500s.
    """
    name = ((user.timezone if user is not None else None) or "").strip()
    if not name:
        return UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


def local_date(moment: datetime, zone) -> date:
    """Which calendar day a stored (naive, UTC) instant falls on for the reader."""
    return moment.replace(tzinfo=UTC).astimezone(zone).date()


def today_for(user: Optional[User]) -> date:
    """
    Today as the user experiences it. The server's own date is never used: it
    runs in UTC while the user may be hours ahead, so for part of every night
    `date.today()` would name yesterday and log expenses to the wrong day.
    """
    return datetime.now(UTC).astimezone(user_zone(user)).date()


def _utc_window(first: date, last: date, zone) -> tuple[datetime, datetime]:
    """
    The UTC instants bounding these calendar days *in `zone`*, as naive
    datetimes to match how created_at is stored. A day is 00:00-23:59:59 local,
    which is a window shifted by the offset once expressed in UTC.
    """
    start = datetime.combine(first, time.min, tzinfo=zone).astimezone(UTC).replace(tzinfo=None)
    end = datetime.combine(last, time.max, tzinfo=zone).astimezone(UTC).replace(tzinfo=None)
    return start, end


def _month_bounds(period: Optional[str], user: Optional[User] = None) -> tuple[datetime, datetime]:
    """
    Parses a "YYYY-MM" string (defaulting to the user's current month) into the
    [start, end] range used to filter expenses for that month.
    """
    if period:
        try:
            year, month = (int(p) for p in period.split("-"))
        except ValueError:
            raise HTTPException(status_code=400, detail="period must be in YYYY-MM format")
    else:
        today = today_for(user)
        year, month = today.year, today.month

    days_in_month = monthrange(year, month)[1]
    return _utc_window(date(year, month, 1), date(year, month, days_in_month), user_zone(user))


def _date_range(
    period: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    user: Optional[User] = None,
) -> tuple[datetime, datetime]:
    """
    The period sheet in the app offers ranges a single "YYYY-MM" can't
    express (a week, a year, the trailing 12 months), so every read endpoint
    also accepts an explicit start/end pair of "YYYY-MM-DD" dates. `period`
    stays the default so existing callers keep working unchanged.
    """
    if start or end:
        if not (start and end):
            raise HTTPException(status_code=400, detail="start and end must be given together")
        try:
            first = datetime.strptime(start, "%Y-%m-%d")
            last = datetime.strptime(end, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="start and end must be in YYYY-MM-DD format")
        if last < first:
            raise HTTPException(status_code=400, detail="end must not be before start")
        return _utc_window(first.date(), last.date(), user_zone(user))
    return _month_bounds(period, user)


# --- App account endpoints (email/password + JWT) -------------------------


def _normalize_email(email: str) -> str:
    """
    The canonical form of an address: lowercased and trimmed.

    Addresses are case-insensitive in practice - nobody thinks of
    Alex@example.com and alex@example.com as two accounts - and the social
    providers hand us a lowercased address regardless. Storing and comparing
    one form is what keeps a password signup and a Google sign-in landing on
    the same row.
    """
    return (email or "").strip().lower()


def _user_by_email(db: Session, email: str) -> Optional[User]:
    """
    Finds an account by address, ignoring case.

    Every way into an account goes through here. A case-sensitive lookup used
    to let a second account exist for the same address, after which a login,
    a reset or a social sign-in could each land on a different one.
    """
    return db.query(User).filter(func.lower(User.email) == _normalize_email(email)).first()


def _give_starter_categories(db: Session, user: User, lang: str) -> None:
    """
    Fills a new account's category list, and tops up an older one that never
    got past the signup quiz this replaced.

    Only names the account does not already have are added, so running it
    again on an account that kept its fallback category adds the rest rather
    than a second "Other".
    """
    existing = {
        name.strip().lower()
        for (name,) in db.query(BudgetCategory.name).filter(BudgetCategory.user_id == user.id)
    }
    has_fallback = bool(existing & FALLBACK_NAMES)
    for name, icon in starter_categories(lang):
        key = name.strip().lower()
        if key in existing:
            continue
        # The catch-all counts as present under any language's name, so an
        # account topped up in a second language does not end up with both
        # "Other" and "Altele".
        if key in FALLBACK_NAMES and has_fallback:
            continue
        db.add(BudgetCategory(user_id=user.id, name=name, icon=icon))
    user.onboarded = True
    db.commit()


@router.post("/api/auth/signup", response_model=TokenResponse)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    existing = _user_by_email(db, payload.email)
    if existing is not None:
        raise HTTPException(status_code=400, detail="An account with this email already exists")

    user = User(email=_normalize_email(payload.email), hashed_password=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)

    _give_starter_categories(db, user, payload.lang)

    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/api/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = _user_by_email(db, payload.email)
    invalid = HTTPException(status_code=401, detail="Incorrect email or password")
    if user is None or user.hashed_password is None:
        raise invalid
    if not verify_password(payload.password, user.hashed_password):
        raise invalid

    return LoginResponse(access_token=create_access_token(user.id))


@router.post("/api/auth/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = _user_by_email(db, payload.email)
    # Always the same response either way, so this endpoint can't be used to
    # probe which emails have accounts.
    if user is not None and user.hashed_password is not None:
        code = issue_otp(db, user, "reset")
        send_otp_email(user.email, code, "reset")
    return {"sent": True}


@router.post("/api/auth/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    user = _user_by_email(db, payload.email)
    invalid = HTTPException(status_code=401, detail="Incorrect or expired code")
    if user is None or not consume_otp(db, user, "reset", payload.code):
        raise invalid

    user.hashed_password = hash_password(payload.new_password)
    db.commit()
    return {"reset": True}


# --- Social sign-in (Google / Apple / GitHub) -----------------------------
# A third way into the same User rows. See app/oauth.py for the flow and for
# why the code exchange happens here rather than in the browser.


@router.get("/api/auth/providers")
def list_oauth_providers():
    """Which buttons the login screen should draw - empty if none are configured."""
    return {"providers": oauth.enabled_providers()}


@router.get("/api/auth/oauth/{provider}/start")
def start_oauth(provider: str, redirect_uri: str, request: Request):
    if not oauth.is_configured(provider):
        raise HTTPException(status_code=404, detail="This sign-in method isn't available")
    try:
        target = oauth.check_redirect(redirect_uri)
    except oauth.OAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))

    url = oauth.authorize_url(
        provider,
        oauth.callback_url(provider, str(request.base_url)),
        oauth.encode_state(provider, target),
    )
    return RedirectResponse(url, status_code=302)


@router.get("/api/auth/oauth/{provider}/callback")
def finish_oauth(provider: str, request: Request, code: str = "", state: str = "", db: Session = Depends(get_db)):
    return _complete_oauth(provider, code, state, request, db)


@router.post("/api/auth/oauth/{provider}/callback")
async def finish_oauth_form_post(provider: str, request: Request, db: Session = Depends(get_db)):
    """Apple answers with response_mode=form_post, so its callback is a POST."""
    form = await request.form()
    return _complete_oauth(provider, str(form.get("code") or ""), str(form.get("state") or ""), request, db)


def _complete_oauth(provider: str, code: str, state: str, request: Request, db: Session):
    """
    Hands the browser back to the frontend either way: the app JWT in the URL
    fragment on success, an error code on failure. A fragment is used rather
    than a query string so the token never reaches a server log or a Referer
    header - the frontend reads it and strips it from the address bar.
    """
    if not oauth.is_configured(provider):
        raise HTTPException(status_code=404, detail="This sign-in method isn't available")

    try:
        redirect_uri = oauth.decode_state(provider, state)
    except oauth.OAuthError as e:
        # No trusted redirect target, so there's nowhere safe to send them.
        raise HTTPException(status_code=400, detail=str(e))

    try:
        if not code:
            raise oauth.OAuthError("The sign-in was cancelled")
        tokens = oauth.exchange_code(provider, code, oauth.callback_url(provider, str(request.base_url)))
        email, subject, display_name = oauth.fetch_identity(provider, tokens)
    except oauth.OAuthError as e:
        return RedirectResponse(f"{redirect_uri}#oauth_error={quote(str(e))}", status_code=302)

    user = _user_by_email(db, email)
    if user is None:
        # New account: no password is ever set. A social sign-in carries no
        # language, so the starter set lands in English and is renamed like
        # any other category.
        user = User(email=email, oauth_provider=provider, oauth_sub=subject, display_name=display_name)
        db.add(user)
        db.commit()
        db.refresh(user)
        _give_starter_categories(db, user, "en")
    else:
        user.oauth_provider = provider
        user.oauth_sub = subject
        if not user.display_name and display_name:
            user.display_name = display_name
        db.commit()

    return RedirectResponse(f"{redirect_uri}#token={create_access_token(user.id)}", status_code=302)


@router.get("/api/me")
def get_me(
    lang: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # An account created before the signup quiz was dropped may still be
    # sitting on the single fallback category it got at signup, with no way
    # left to finish. The first read of the profile tops it up instead.
    if not user.onboarded:
        _give_starter_categories(db, user, lang or "en")

    return {
        "id": user.id,
        "email": user.email,
        "currency": user.currency,
        "timezone": user.timezone,
        "oauth_provider": user.oauth_provider,
        "has_password": user.hashed_password is not None,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.delete("/api/me")
def delete_account(
    payload: Optional[DeleteAccountRequest] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Erases the account and everything belonging to it. This is what the privacy
    policy promises, so it deletes rather than deactivates - nothing is kept
    behind a flag.

    An account with a password has to re-enter it. The bearer token alone is a
    weaker proof for something irreversible: it lives in browser storage for 30
    days, so an unattended session would otherwise be enough to wipe the
    account. A social-only account has no password to ask for, and its token is
    all there is.
    """
    if user.hashed_password is not None:
        if payload is None or not payload.password:
            raise HTTPException(status_code=400, detail="Enter your password to delete your account")
        if not verify_password(payload.password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Incorrect password")

    user_id = user.id

    # Expenses first: they point at budget_categories, so removing those
    # before the rows referencing them would trip the foreign keys.
    deleted = {
        "expenses": db.query(Expense).filter(Expense.user_id == user_id).delete(synchronize_session=False),
        "categories": db.query(BudgetCategory).filter(BudgetCategory.user_id == user_id).delete(synchronize_session=False),
        "otp_codes": db.query(OtpCode).filter(OtpCode.user_id == user_id).delete(synchronize_session=False),
    }
    db.query(User).filter(User.id == user_id).delete(synchronize_session=False)
    db.commit()

    # One commit for the lot, so a failure part-way leaves the account whole
    # rather than half-erased.
    return {"deleted": True, **deleted}


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


@router.put("/api/me/timezone")
def update_timezone(
    payload: TimezoneUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Sets which timezone the user's calendar days are measured in. Stored
    instants never change - this only affects which day they are counted under,
    so switching zones re-files existing expenses rather than editing them.
    """
    name = payload.timezone.strip()
    if name:
        try:
            ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(status_code=400, detail="Unknown time zone")
    user.timezone = name or None
    db.commit()
    return {"timezone": user.timezone, "today": today_for(user).isoformat()}


@router.get("/api/me/stats")
def get_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    total_all_time = (
        db.query(func.sum(Expense.amount)).filter(Expense.user_id == user.id).scalar() or 0.0
    )

    start, end = _month_bounds(None, user)
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

    return {
        "total_all_time": round(total_all_time, 2),
        "total_this_month": round(total_this_month, 2),
        "monthly_average": round(monthly_average, 2),
        "top_category": top_category_row[0] if top_category_row else None,
        "top_category_total": round(top_category_row[1], 2) if top_category_row else None,
        "member_since": user.created_at.isoformat() if user.created_at else None,
        "months_tracked": len(by_month),
    }


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


# --- Exchange rates -------------------------------------------------------
# Read-only and identical for everyone, so no auth: these are published
# reference rates, not anything belonging to an account.


@router.get("/api/rates")
def get_rates():
    """
    Today's rates for the currencies the app shows: EUR/USD/GBP straight from
    BNR, BTC/ETH from a crypto price source with BNR's USD rate doing the RON
    leg. Each row says which, since a central bank does not publish a bitcoin
    price and the page shouldn't imply otherwise.
    """
    try:
        return bnr.page_rates()
    except bnr.RatesUnavailable:
        raise HTTPException(status_code=503, detail="Exchange rates are unavailable right now - try again shortly")


# --- Budget view: the app's version of the spreadsheet ---------------------
# A "month" is just a date filter over Expense rows, not a duplicated set of
# category rows - the category list (names, targets, icons) is shared across
# every month you look at.


@router.get("/api/budget")
def get_budget(
    period: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start, end = _date_range(period, start, end, user)
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


def _convert_for_user(amount: float, currency: Optional[str], user: User) -> tuple[float, Optional[float], Optional[str], Optional[float]]:
    """
    Resolves an amount that may have been entered in another currency.

    Returns (amount_in_user_currency, original_amount, original_currency,
    fx_rate). The last three are None when no conversion happened, which keeps
    a same-currency expense indistinguishable from one logged before this
    existed.

    Conversion failures are a 503, not a silent fallback to 1:1 - filing €25
    as 25 lei would corrupt every total that touches it, and the user can
    always re-enter the amount in their own currency instead.
    """
    code = (currency or "").strip().upper()
    own = (user.currency or "RON").strip().upper()
    if not code or code == own:
        return amount, None, None, None

    try:
        converted, rate = bnr.convert(amount, code, own)
    except bnr.RatesUnavailable:
        raise HTTPException(status_code=503, detail="Exchange rates are unavailable right now - try again shortly")
    except KeyError as unknown:
        raise HTTPException(status_code=400, detail=f"No BNR exchange rate for {unknown.args[0]}")

    return converted, amount, code, rate


def _expense_to_dict(e: Expense, zone=UTC) -> dict:
    return {
        "id": e.id,
        "amount": e.amount,
        "original_amount": e.original_amount,
        "original_currency": e.original_currency,
        "fx_rate": e.fx_rate,
        "category_id": e.category_id,
        "category_name": e.matched_category.name if e.matched_category else None,
        "category_icon": e.matched_category.icon if e.matched_category else None,
        "note": e.raw_message,
        "date": local_date(e.created_at, zone).strftime("%Y-%m-%d"),
    }


@router.get("/api/expenses")
def list_expenses_for_period(
    period: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start, end = _date_range(period, start, end, user)
    expenses = (
        db.query(Expense)
        .filter(Expense.user_id == user.id, Expense.created_at >= start, Expense.created_at <= end)
        # Rows logged from the app carry a date, not a time, so same-day rows
        # would otherwise come back in an arbitrary order - the id breaks the
        # tie so the newest one always sorts first within its day.
        .order_by(Expense.created_at.desc(), Expense.id.desc())
        .all()
    )
    return [_expense_to_dict(e, user_zone(user)) for e in expenses]


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

    amount, original_amount, original_currency, fx_rate = _convert_for_user(payload.amount, payload.currency, user)

    expense = Expense(
        user_id=user.id,
        amount=amount,
        original_amount=original_amount,
        original_currency=original_currency,
        fx_rate=fx_rate,
        category=category.name if category else None,
        category_id=category.id if category else None,
        raw_message=payload.note or (category.name if category else "Manual entry"),
        created_at=_parse_date_or_400(payload.date),
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return _expense_to_dict(expense, user_zone(user))


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
        # Editing the amount re-runs the conversion at today's rate rather than
        # reusing the stored one: the stored rate explains the original entry,
        # and a correction is a new decision about a new number.
        amount, original_amount, original_currency, fx_rate = _convert_for_user(payload.amount, payload.currency, user)
        expense.amount = amount
        expense.original_amount = original_amount
        expense.original_currency = original_currency
        expense.fx_rate = fx_rate
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
        # An expense logged from the app has no note of its own: it is labelled
        # with its category's name, and the app shows that label as the row's
        # title. So when the category moves, the auto-label has to move with it
        # - otherwise a recategorised row keeps announcing the old category.
        #
        # A label counts as auto-generated if it reads as any of this user's
        # category names (not just the current one, so a row that already
        # drifted gets repaired) or as the placeholder a manual entry gets.
        # Anything else is something the user wrote, and stays.
        auto_labels = {
            name for (name,) in db.query(BudgetCategory.name).filter(BudgetCategory.user_id == user.id)
        }
        auto_labels.update({"Manual entry", ""})
        expense.category_id = category.id
        expense.category = category.name
        if (expense.raw_message or "").strip() in auto_labels:
            expense.raw_message = category.name
    if payload.date is not None:
        expense.created_at = _parse_date_or_400(payload.date)
    if payload.note is not None:
        expense.raw_message = payload.note

    db.commit()
    db.refresh(expense)
    return _expense_to_dict(expense, user_zone(user))


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


def _current_period(user: Optional[User] = None) -> str:
    today = today_for(user)
    return f"{today.year:04d}-{today.month:02d}"


# --- Spreadsheet import --------------------------------------------------
# Uploads the same shape of file as the user's own Google Sheets budget
# ("<Month> Budget Tracker") and populates categories and expenses
# from it. See app/importer.py for the parsing rules.


@router.post("/api/import/spreadsheet")
async def import_spreadsheet(
    file: UploadFile = File(...),
    period: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    content = await file.read()
    period = period or guess_period_from_filename(file.filename or "") or _current_period(user)

    try:
        result = parse_workbook(content, file.filename or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not result.categories:
        raise HTTPException(status_code=400, detail="Couldn't find any spending rows in this file")

    existing_categories = {c.name.lower(): c for c in db.query(BudgetCategory).filter(BudgetCategory.user_id == user.id).all()}
    categories_created = 0
    categories_updated = 0

    # Re-importing the same period replaces that period's prior import, so
    # running the same file twice doesn't double the totals.
    period_start, period_end = _month_bounds(period, user)
    db.query(Expense).filter(
        Expense.user_id == user.id,
        Expense.source == "import",
        Expense.created_at >= period_start,
        Expense.created_at <= period_end,
    ).delete(synchronize_session=False)

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

    db.commit()

    return {
        "period": period,
        "categories_created": categories_created,
        "categories_updated": categories_updated,
        "total_imported": round(sum(r.amount for r in result.categories), 2),
        "warnings": result.warnings,
    }
