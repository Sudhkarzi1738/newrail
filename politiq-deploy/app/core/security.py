import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings
from app.core.errors import AppError


class AuthError(AppError):
    status_code, code = 401, "unauthorized"


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode(), hashed.encode())
    except ValueError:
        return False


def _make(sub: int, typ: str, ttl: timedelta, token_version: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(sub), "typ": typ, "tv": token_version, "iat": now, "exp": now + ttl, "jti": uuid.uuid4().hex},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def create_access_token(user_id: int, token_version: int) -> str:
    return _make(user_id, "access", timedelta(minutes=settings.access_token_minutes), token_version)


def create_refresh_token(user_id: int, token_version: int) -> str:
    return _make(user_id, "refresh", timedelta(days=settings.refresh_token_days), token_version)


def decode_token(token: str, expected_type: str) -> dict:
    try:
        data = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as e:
        raise AuthError("Invalid or expired token") from e
    if data.get("typ") != expected_type:
        raise AuthError("Wrong token type")
    return data
