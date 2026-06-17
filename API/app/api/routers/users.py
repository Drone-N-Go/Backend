"""
app/api/routers/users.py
-------------------------
User management endpoints:
  GET  /api/users/me/profile
  PUT  /api/users/me/profile
  POST /api/users/me/change-password
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.security import hash_password, verify_password
from app.db.session import get_db
from app.models.admin_profile import AdminProfile
from app.models.user import User
from app.schemas.user import UserResponse, UserUpdateRequest
from app.services import user_service

router = APIRouter(prefix="/users", tags=["Users"])


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, description="Minimum 8 characters")


@router.get(
    "/me/profile",
    response_model=UserResponse,
    summary="Get the authenticated user's profile",
)
async def get_my_profile(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


@router.put(
    "/me/profile",
    response_model=UserResponse,
    summary="Update the authenticated user's profile",
)
async def update_my_profile(
    body: UserUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    updated = await user_service.update_user_profile(current_user, body, db)
    return UserResponse.model_validate(updated)


@router.post(
    "/me/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change the authenticated user's password",
)
async def change_my_password(
    body: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect.",
        )
    current_user.password_hash = hash_password(body.new_password)

    # Clear the forced-change flag if this user has an admin profile.
    result = await db.execute(
        select(AdminProfile).where(AdminProfile.user_id == current_user.id)
    )
    admin_profile = result.scalar_one_or_none()
    if admin_profile and admin_profile.must_change_password:
        admin_profile.must_change_password = False
        db.add(admin_profile)

    await db.commit()
    return None
