from typing import Optional
from pydantic import BaseModel, EmailStr


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    lang: str = "en"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginResponse(BaseModel):
    requires_otp: bool = False
    access_token: Optional[str] = None
    token_type: str = "bearer"


class VerifyOtpRequest(BaseModel):
    email: EmailStr
    code: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str
    new_password: str


class TwoFactorUpdateRequest(BaseModel):
    enabled: bool


class DeleteAccountRequest(BaseModel):
    # Required only for accounts that have a password; a social-only account
    # has none to check, and the bearer token is the proof of identity there.
    password: Optional[str] = None


class OnboardingRequest(BaseModel):
    answers: dict[str, str]  # {question_id: option_id}
    lang: str = "en"


class ChatMessageRequest(BaseModel):
    text: str


class ChatMessageResponse(BaseModel):
    amount: float | None = None
    category: str | None = None
    over_budget: bool = False
    spent: float | None = None  # this category's total for the current month, if over_budget
    target: float | None = None
    parsed: bool = True  # false if the message didn't parse - frontend shows its own localized error
    # Set only when the message named a currency other than the user's own, so
    # the reply can confirm what was converted rather than echoing a number the
    # sender never typed.
    original_amount: float | None = None
    original_currency: str | None = None


class CategoryOut(BaseModel):
    id: int
    name: str
    icon: str
    target: Optional[float] = None
    tag: Optional[str] = None


class ExpenseCreateRequest(BaseModel):
    amount: float
    category_id: Optional[int] = None
    account_id: Optional[int] = None
    date: Optional[str] = None  # "YYYY-MM-DD"; defaults to today
    note: Optional[str] = None
    # The currency `amount` is written in. None (or the account's own
    # currency) means no conversion; anything else is converted at the BNR
    # reference rate and stored in the account's currency, with the original
    # kept alongside it.
    currency: Optional[str] = None


class ExpenseUpdateRequest(BaseModel):
    amount: Optional[float] = None
    category_id: Optional[int] = None
    account_id: Optional[int] = None
    clear_category: bool = False
    clear_account: bool = False
    date: Optional[str] = None  # "YYYY-MM-DD"
    note: Optional[str] = None
    currency: Optional[str] = None  # re-converts `amount` from this currency; see ExpenseCreateRequest


class ExpenseOut(BaseModel):
    id: int
    amount: float  # always in the user's own currency
    original_amount: Optional[float] = None  # what was actually spent, if it was another currency
    original_currency: Optional[str] = None
    fx_rate: Optional[float] = None
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    category_icon: Optional[str] = None
    account_id: Optional[int] = None
    account_name: Optional[str] = None
    note: str
    date: str  # "YYYY-MM-DD"


class CategoryCreateRequest(BaseModel):
    name: str
    target: Optional[float] = None
    icon: Optional[str] = None
    tag: Optional[str] = None  # "Needs" / "Wants" / "Savings"


class CategoryUpdateRequest(BaseModel):
    name: Optional[str] = None
    target: Optional[float] = None
    icon: Optional[str] = None
    tag: Optional[str] = None
    clear_target: bool = False  # explicit flag: target=None alone can't distinguish "unset" from "don't change"
    clear_tag: bool = False


class CurrencyUpdateRequest(BaseModel):
    currency: str


class TimezoneUpdateRequest(BaseModel):
    timezone: str  # an IANA name, or "" to fall back to UTC


class ProfileUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None  # data URL; empty string clears it


class GoalUpdateRequest(BaseModel):
    wants_pct: float
    needs_pct: float
    savings_pct: float


class IncomeCreateRequest(BaseModel):
    name: str
    amount: float
    period: Optional[str] = None  # "YYYY-MM"; defaults to current month


class IncomeUpdateRequest(BaseModel):
    name: Optional[str] = None
    amount: Optional[float] = None


class AccountCreateRequest(BaseModel):
    name: str
    kind: Optional[str] = None  # "Current" / "Debit" / "Wallet"
    last4: Optional[str] = None
    balance: float = 0.0
    icon: Optional[str] = None


class AccountUpdateRequest(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    last4: Optional[str] = None
    balance: Optional[float] = None
    icon: Optional[str] = None
    clear_kind: bool = False
    clear_last4: bool = False
