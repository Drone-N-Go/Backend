"""
app/schemas/contact.py
------------------------
Pydantic v2 request/response schemas for the public website contact form.
"""

from pydantic import BaseModel, EmailStr, Field


class ContactFormRequest(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    message: str = Field(..., min_length=1, max_length=4000)


class ContactFormResponse(BaseModel):
    ok: bool = True
