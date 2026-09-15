"""
app/api/routers/contact.py
-----------------------------
Public website contact form endpoint (no auth — anyone can submit):
  POST /api/contact
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.contact import ContactFormRequest, ContactFormResponse
from app.services import contact_service

router = APIRouter(prefix="/contact", tags=["Contact"])


@router.post(
    "",
    response_model=ContactFormResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit the public website contact form",
)
async def submit_contact_form(
    form: ContactFormRequest, db: AsyncSession = Depends(get_db)
):
    await contact_service.submit_contact_form(form, db)
    return ContactFormResponse()
