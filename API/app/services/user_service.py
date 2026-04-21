"""
app/services/user_service.py
-----------------------------
Business logic for user profile management and admin user queries.
"""

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking
from app.models.user import User
from app.schemas.user import UserListResponse, UserResponse, UserUpdateRequest


async def get_all_users(
    db: AsyncSession, skip: int = 0, limit: int = 50, role: str | None = None
) -> UserListResponse:
    query = select(User)
    count_query = select(func.count()).select_from(User)

    if role:
        query = query.where(User.role == role)
        count_query = count_query.where(User.role == role)

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    result = await db.execute(query.offset(skip).limit(limit))
    users = result.scalars().all()

    return UserListResponse(
        items=[UserResponse.model_validate(u) for u in users],
        total=total,
        skip=skip,
        limit=limit,
    )


async def get_user_by_id(user_id: str, db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


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


async def get_user_rentals(
    user_id: str, db: AsyncSession, skip: int = 0, limit: int = 50
) -> dict:
    # Verify user exists
    await get_user_by_id(user_id, db)

    count_result = await db.execute(
        select(func.count()).select_from(Booking).where(Booking.user_id == user_id)
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(Booking)
        .where(Booking.user_id == user_id)
        .order_by(Booking.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    bookings = result.scalars().all()

    return {"items": bookings, "total": total, "skip": skip, "limit": limit}
