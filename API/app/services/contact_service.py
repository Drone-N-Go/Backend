"""
app/services/contact_service.py
----------------------------------
Public website contact form: save-then-notify.

The submission is written to `contact_submissions` FIRST. The Resend
notification email is attempted after, and a failure there is logged but
does not fail the request or roll back the insert -- the visitor always
sees success once their message is durably saved, and `email_sent` on the
row records whether the notification actually went out. This is the
deliberate fix for the previous behavior (email-only, no persistence),
where a Resend outage or a bad API key meant a submitted message was lost
with no record anywhere.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact_submission import ContactSubmission
from app.schemas.contact import ContactFormRequest
from app.services import email_service

logger = logging.getLogger(__name__)


async def submit_contact_form(
    form: ContactFormRequest, db: AsyncSession
) -> ContactSubmission:
    submission = ContactSubmission(
        first_name=form.first_name,
        last_name=form.last_name,
        email=form.email,
        message=form.message,
    )
    db.add(submission)
    await db.flush()  # assigns id/created_at; app.db.session.get_db commits at request end

    try:
        await email_service.send_contact_form_email(form)
        submission.email_sent = True
    except Exception:
        logger.exception(
            "Contact form submission %s saved but notification email failed to send",
            submission.id,
        )

    return submission
