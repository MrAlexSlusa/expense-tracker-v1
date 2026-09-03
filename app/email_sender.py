"""
Sends transactional email (OTP codes for login 2FA and password reset) via
Resend's HTTP API. Mirrors the pattern in app/sheets.py: if RESEND_API_KEY
isn't configured, this doesn't fail the request - it logs the email to the
console instead, so OTP flows are fully testable locally before you've set
up a real provider. Swap in a different provider later by editing only this
file; nothing in api.py needs to know how the email actually gets sent.
"""

import os
import httpx

RESEND_API_URL = "https://api.resend.com/emails"


def send_email(to: str, subject: str, html: str) -> bool:
    api_key = os.environ.get("RESEND_API_KEY")
    from_address = os.environ.get("RESEND_FROM_EMAIL", "Expense Tracker <onboarding@resend.dev>")

    if not api_key:
        print(f"[email not configured - would send] To: {to} | Subject: {subject}\n{html}")
        return True

    try:
        response = httpx.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"from": from_address, "to": [to], "subject": subject, "html": html},
            timeout=10,
        )
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Failed to send email to {to}: {e}")
        return False


def send_otp_email(to: str, code: str, purpose: str) -> bool:
    if purpose == "login":
        subject = "Your login code"
        heading = "Here's your login code"
    else:
        subject = "Reset your password"
        heading = "Here's your password reset code"

    html = f"""
    <div style="font-family: sans-serif; max-width: 420px; margin: 0 auto;">
      <h2>{heading}</h2>
      <p style="font-size: 32px; font-weight: 700; letter-spacing: 6px;">{code}</p>
      <p style="color: #666;">This code expires in 10 minutes. If you didn't request this, you can ignore this email.</p>
    </div>
    """
    return send_email(to, subject, html)
