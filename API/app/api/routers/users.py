"""
app/api/routers/users.py
-------------------------
User management endpoints:
  GET  /api/users                      (admin)
  GET  /api/users/me/profile
  PUT  /api/users/me/profile
  GET  /api/users/{user_id}            (admin)
  GET  /api/users/{user_id}/rentals    (admin)
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.booking import BookingListResponse, BookingResponse
from app.schemas.user import UserListResponse, UserResponse, UserUpdateRequest
from app.services import user_service

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "",
    response_model=UserListResponse,
    summary="List all users — admin only",
)
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    role: str | None = Query(None, pattern="^(user|admin)$"),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    return await user_service.get_all_users(db, skip=skip, limit=limit, role=role)


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


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Get a specific user by ID — admin only",
)
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    user = await user_service.get_user_by_id(user_id, db)
    return UserResponse.model_validate(user)


@router.get(
    "/{user_id}/rentals",
    response_model=BookingListResponse,
    summary="Get rental history for a specific user — admin only",
)
async def get_user_rentals(
    user_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    data = await user_service.get_user_rentals(user_id, db, skip=skip, limit=limit)
    return BookingListResponse(
        items=[BookingResponse.model_validate(b) for b in data["items"]],
        total=data["total"],
        skip=data["skip"],
        limit=data["limit"],
    )
