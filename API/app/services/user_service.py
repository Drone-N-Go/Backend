"""
app/services/user_service.py
-----------------------------
Business logic for user profile management.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.user import UserUpdateRequest


async def update_user_profile(
    user: User, body: UserUpdateRequest, db: AsyncSession
) -> User:
    if body.first_name is not None:
        user.first_name = body.first_name
    if body.last_name is not None:
        user.last_name = body.last_name
    if body.address is not None:
        user.address = body.address
    if body.school is not None:
        user.school = body.school

    db.add(user)
    await db.flush()
    return user
