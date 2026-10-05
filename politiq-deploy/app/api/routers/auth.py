from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.config import settings
from app.core.errors import AppError
from app.core.rate_limit import RateLimiter
from app.core.security import (
    AuthError, create_access_token, create_refresh_token, decode_token, hash_password, verify_password,
)
from app.db.session import get_db
from app.models.platform import Role, User
from app.schemas.auth import LoginIn, RefreshIn, RegisterIn, TokenPair, UserOut
from app.services.audit import audit

# stricter limit for credential endpoints
auth_limit = RateLimiter(lambda: 10, "auth")
router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(auth_limit)])


def _pair(u: User) -> TokenPair:
    return TokenPair(access_token=create_access_token(u.id, u.token_version),
                     refresh_token=create_refresh_token(u.id, u.token_version))


@router.post("/register", response_model=TokenPair, status_code=201)
async def register(body: RegisterIn, db: AsyncSession = Depends(get_db)):
    if await db.scalar(select(User.id).where(User.email == body.email.lower())):
        raise AppError("Email already registered", extra={})
    user = User(email=body.email.lower(), hashed_password=hash_password(body.password),
                full_name=body.full_name, organization=body.organization, role=Role.PUBLIC)
    db.add(user)
    await db.flush()
    return _pair(user)


@router.post("/login", response_model=TokenPair)
async def login(body: LoginIn, request: Request, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.email == body.email.lower()))
    if not user or not user.is_active or not verify_password(body.password, user.hashed_password):
        await audit("login_failed", user_id=user.id if user else None, request=request)
        raise AuthError("Invalid credentials")
    return _pair(user)


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshIn, db: AsyncSession = Depends(get_db)):
    data = decode_token(body.refresh_token, "refresh")
    user = await db.get(User, int(data["sub"]))
    if not user or not user.is_active or user.token_version != data.get("tv"):
        raise AuthError("Session is no longer valid")
    return _pair(user)


@router.post("/logout", status_code=204)
async def logout(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    user.token_version += 1  # invalidates every outstanding access + refresh token for this user
    db.add(user)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)):
    return user
