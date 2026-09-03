"""
Email/password auth for the app frontend, separate from the phone-number
identity used by the WhatsApp webhook. Both paths land on the same User
model (see app/models.py) so a future "link your WhatsApp number" feature
is just filling in a column, not a migration.
"""

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, OtpCode

OTP_EXPIRE_MINUTES = 10

# Dev fallback only - always set a real JWT_SECRET_KEY env var in production,
# otherwise every restart invalidates existing tokens (this key is random)
# and any two instances of the process would disagree on what's valid.
SECRET_KEY = os.environ.get("JWT_SECRET_KEY") or os.urandom(32).hex()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30  # 30 days - mobile app, not a browser session

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def hash_password(password: str) -> str:
    # bcrypt caps input at 72 bytes; truncate rather than error on long passwords.
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8")[:72], hashed_password.encode("utf-8"))


def create_access_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token is None:
        raise unauthorized

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise unauthorized
    except JWTError:
        raise unauthorized

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise unauthorized
    return user


def issue_otp(db: Session, user: User, purpose: str) -> str:
    """Creates and stores a fresh 6-digit code, returning the plaintext to email."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    otp = OtpCode(
        user_id=user.id,
        code_hash=hash_password(code),
        purpose=purpose,
        expires_at=datetime.utcnow() + timedelta(minutes=OTP_EXPIRE_MINUTES),
    )
    db.add(otp)
    db.commit()
    return code


def consume_otp(db: Session, user: User, purpose: str, code: str) -> bool:
    """Checks `code` against this user's unexpired, unused codes for `purpose`; marks it used on success."""
    candidates = (
        db.query(OtpCode)
        .filter(
            OtpCode.user_id == user.id,
            OtpCode.purpose == purpose,
            OtpCode.used == False,  # noqa: E712
            OtpCode.expires_at >= datetime.utcnow(),
        )
        .all()
    )
    for otp in candidates:
        if verify_password(code, otp.code_hash):
            otp.used = True
            db.commit()
            return True
    return False
