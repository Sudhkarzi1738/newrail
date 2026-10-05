from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Forbidden, PaywallError
from app.core.security import AuthError, decode_token
from app.db.session import get_db
from app.models.platform import ResourceType, Role, User
from app.services.access import has_access
from app.services.audit import audit

bearer = HTTPBearer(auto_error=False)


async def current_user_optional(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: AsyncSession = Depends(get_db)
) -> User | None:
    if creds is None:
        return None
    data = decode_token(creds.credentials, "access")
    user = await db.get(User, int(data["sub"]))
    if not user or not user.is_active or user.token_version != data.get("tv"):
        raise AuthError("Session is no longer valid")
    return user


async def current_user(user: User | None = Depends(current_user_optional)) -> User:
    if user is None:
        raise AuthError("Authentication required")
    return user


async def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != Role.ADMIN:
        raise Forbidden("Admin only")
    return user


def require_paid(rtype: ResourceType, path_param: str):
    """Dependency factory. Verifies entitlement for the resource id taken from the URL path.
    No handler runs (and no paid query executes) unless this passes."""

    async def dep(request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> User:
        rid = int(request.path_params[path_param])
        if not await has_access(db, user, rtype, rid):
            await audit("paid_denied", user_id=user.id, request=request, resource_type=rtype.value, resource_id=rid)
            raise PaywallError(
                "A paid subscription or report purchase is required for this data.",
                extra={"cta": {"action": "request_full_report", "endpoint": "/api/v1/report-requests",
                               "resource_type": rtype.value, "resource_id": rid}},
            )
        await audit("paid_access", user_id=user.id, request=request, resource_type=rtype.value, resource_id=rid,
                    meta={"path": request.url.path})
        return user

    return dep
