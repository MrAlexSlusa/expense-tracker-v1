"""
Receives inbound WhatsApp messages in Twilio's webhook format.

Twilio POSTs form-encoded data with (at minimum) 'From' and 'Body' fields
when a WhatsApp message comes in. This shape is stable regardless of what
you eventually swap in - a real Twilio account, a different provider, or
your own test script - so building against it now means the switch later
is a config change, not a rewrite.
"""

from fastapi import APIRouter, Form
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from fastapi import Depends

from app.database import get_db
from app.models import User, Expense
from app.parser import parse_expense_message
from app.utils import normalize_phone
from app.sheets import record_expense

router = APIRouter()


def _get_or_create_user(db: Session, phone_number: str) -> User:
    phone_number = normalize_phone(phone_number)
    user = db.query(User).filter(User.phone_number == phone_number).first()
    if user is None:
        user = User(phone_number=phone_number)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


@router.post("/webhook/whatsapp")
def receive_whatsapp_message(
    From: str = Form(...),
    Body: str = Form(...),
    db: Session = Depends(get_db),
):
    parsed = parse_expense_message(Body)

    if parsed is None:
        reply = (
            "Couldn't find an amount in that message. "
            "Try something like '25 groceries' or '12.50 coffee'."
        )
        return _twiml_reply(reply)

    user = _get_or_create_user(db, From)
    expense = Expense(
        user_id=user.id,
        amount=parsed.amount,
        category=parsed.category,
        raw_message=Body,
    )
    db.add(expense)
    db.commit()

    # Sheet write happens after the database commit and never blocks the
    # reply - the database is the source of truth, the sheet is a mirror.
    sync_result = record_expense(category=parsed.category, amount=parsed.amount)

    if sync_result.success:
        reply = f"✅ Logged {parsed.amount:.2f} to {sync_result.category}"
    else:
        category_label = parsed.category or "uncategorized"
        reply = (
            f"Logged {parsed.amount:.2f} ({category_label}), "
            f"but the sheet wasn't updated: {sync_result.reason}"
        )
    return _twiml_reply(reply)


def _twiml_reply(message: str) -> PlainTextResponse:
    """Twilio expects a TwiML XML response to send a reply back to the user."""
    twiml = f"<?xml version='1.0' encoding='UTF-8'?><Response><Message>{message}</Message></Response>"
    return PlainTextResponse(content=twiml, media_type="application/xml")
