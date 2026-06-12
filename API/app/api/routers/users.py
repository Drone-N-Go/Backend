"""
app/api/routers/users.py
-------------------------
User management endpoints:
  GET  /api/users/me/profile
  PUT  /api/users/me/profile
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import UserResponse, UserUpdateRequest
from app.services import user_service

router = APIRouter(prefix="/users", tags=["Users"])


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
