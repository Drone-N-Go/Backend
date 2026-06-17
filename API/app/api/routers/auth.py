"""
app/api/routers/auth.py
------------------------
Authentication endpoints:
  POST /api/auth/register
  POST /api/auth/login
  POST /api/auth/logout
  GET  /api/auth/me
  POST /api/auth/refresh
"""

import logging

from fastapi import APIRouter, Cookie, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import (
    RefreshTokenRequest,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from app.services import auth_service
from app.core.config import get_settings

router = APIRouter(prefix="/auth", tags=["Authentication"])
settings = get_settings()
logger = logging.getLogger(__name__)


def _set_auth_cookies(response: Response, token_data: TokenResponse) -> None:
    """Set httponly auth cookies for browser-based clients."""
    response.set_cookie(
        key="access_token",
        value=token_data.access_token,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        max_age=30 * 60,          # 30 minutes
    )
    response.set_cookie(
        key="refresh_token",
        value=token_data.refresh_token,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        max_age=7 * 24 * 60 * 60,  # 7 days
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=201,
    summary="Register a new user account",
)
async def register(
    body: UserRegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    token_data = await auth_service.register_user(body, request, db)
    _set_auth_cookies(response, token_data)
    return token_data


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login and receive JWT tokens",
)
async def login(
    body: UserLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    token_data = await auth_service.login_user(body.email, body.password, request, db)
    _set_auth_cookies(response, token_data)
    return token_data


@router.post(
    "/logout",
    summary="Clear authentication cookies",
)
async def logout(
    response: Response,
    body: RefreshTokenRequest | None = None,
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    token = body.refresh_token if body else refresh_token
    await auth_service.revoke_refresh_token(token, db)
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return {"message": "Logged out successfully."}


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get the currently authenticated user's profile",
)
async def me(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Exchange a refresh token for a new access token",
)
async def refresh(
    response: Response,
    body: RefreshTokenRequest | None = None,
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    from fastapi import HTTPException, status

    token = body.refresh_token if body else refresh_token
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not provided.",
        )
    token_data = await auth_service.refresh_access_token(token, db)
    _set_auth_cookies(response, token_data)
    return token_data
