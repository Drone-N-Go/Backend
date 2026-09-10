"""
app/services/email_service.py
-------------------------------
Outbound transactional email via Resend. Currently used only for the public
website contact form (see app/api/routers/contact.py), which notifies
CONTACT_NOTIFY_EMAIL and sets Reply-To to the submitter so a reply goes
straight back to them.
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
