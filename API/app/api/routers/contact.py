"""
app/api/routers/contact.py
-----------------------------
Public website contact form endpoint (no auth — anyone can submit):
  POST /api/contact
"""

from fastapi import APIRouter, status

from app.schemas.contact import ContactFormRequest, ContactFormResponse
from app.services import email_service

router = APIRouter(prefix="/contact", tags=["Contact"])


@router.post(
    "",
    response_model=ContactFormResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit the public website contact form",
)
async def submit_contact_form(form: ContactFormRequest):
    await email_service.send_contact_form_email(form)
    return ContactFormResponse()
