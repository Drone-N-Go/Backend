"""
app/services/email_service.py
-------------------------------
Outbound transactional email via Resend. Currently used only for the public
website contact form (see app/api/routers/contact.py), which notifies
CONTACT_NOTIFY_EMAIL and sets Reply-To to the submitter so a reply goes
straight back to them.

Also sends forgot-password codes (added 2026-11-24).
"""

import logging

import resend
from fastapi import HTTPException, status

from app.core.config import get_settings
from app.schemas.contact import ContactFormRequest

logger = logging.getLogger(__name__)
settings = get_settings()


def _escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


async def send_contact_form_email(form: ContactFormRequest) -> None:
    api_key = settings.require_resend_api_key()
    resend.api_key = api_key

    full_name = f"{form.first_name} {form.last_name}"
    safe_message = _escape_html(form.message).replace("\n", "<br>")

    try:
        resend.Emails.send(
            {
                "from": settings.contact_from_email,
                "to": [settings.contact_notify_email],
                "reply_to": form.email,
                "subject": f"New contact form submission from {full_name}",
                "html": (
                    f"<p><strong>Name:</strong> {_escape_html(full_name)}</p>"
                    f"<p><strong>Email:</strong> {_escape_html(form.email)}</p>"
                    f"<p><strong>Message:</strong></p><p>{safe_message}</p>"
                ),
            }
        )
    except Exception:
        logger.exception("Failed to send contact form email via Resend")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not send your message right now. Please try again shortly.",
        )


def send_password_reset_email(to_email: str, first_name: str, code: str, ttl_minutes: int) -> None:
    """Email a one-time password-reset code.

    Raises on failure; the caller logs and swallows it so the API response
    never reveals whether an account exists or whether delivery worked.
    """
    resend.api_key = settings.require_resend_api_key()
    greeting = f"Hi {_escape_html(first_name)}," if first_name else "Hi,"
    resend.Emails.send(
        {
            "from": settings.password_reset_from_email,
            "to": [to_email],
            "subject": f"Your DroneAndGo password reset code: {code}",
            "html": (
                f"<p>{greeting}</p>"
                "<p>Use this code to reset your DroneAndGo password:</p>"
                f'<p style="font-size:28px;font-weight:700;letter-spacing:6px">{code}</p>'
                f"<p>It expires in {ttl_minutes} minutes and can only be used once.</p>"
                "<p>If you didn't ask to reset your password, you can ignore this email. "
                "Your password won't change unless someone enters this code.</p>"
            ),
            "text": (
                f"{'Hi ' + first_name + ',' if first_name else 'Hi,'}\n\n"
                f"Your DroneAndGo password reset code is {code}\n\n"
                f"It expires in {ttl_minutes} minutes and can only be used once. "
                "If you didn't ask to reset your password, ignore this email."
            ),
        }
    )
