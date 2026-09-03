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


class CategoryOut(BaseModel):
    id: int
    name: str
    icon: str
    target: Optional[float] = None
    tag: Optional[str] = None


class ExpenseCreateRequest(BaseModel):
    amount: float
    category_id: Optional[int] = None
    date: Optional[str] = None  # "YYYY-MM-DD"; defaults to today
    note: Optional[str] = None


class ExpenseUpdateRequest(BaseModel):
    amount: Optional[float] = None
    category_id: Optional[int] = None
    clear_category: bool = False
    date: Optional[str] = None  # "YYYY-MM-DD"
    note: Optional[str] = None


class ExpenseOut(BaseModel):
    id: int
    amount: float
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    category_icon: Optional[str] = None
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
