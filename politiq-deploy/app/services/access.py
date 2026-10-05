from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import ReportEntitlement, ResourceType, Role, Subscription, User


async def has_access(db: AsyncSession, user: User, rtype: ResourceType, rid: int) -> bool:
    """Single source of truth for the paywall. Role=PAID alone is NOT enough: access needs a live
    subscription or an unexpired one-time entitlement for this exact resource. Admins always pass."""
    if user.role == Role.ADMIN:
        return True
    now = datetime.now(timezone.utc)
    sub = await db.scalar(
        select(Subscription.id).where(
            Subscription.user_id == user.id, Subscription.cancelled.is_(False),
            Subscription.starts_at <= now, Subscription.ends_at > now,
        ).limit(1)
    )
    if sub:
        return True
    ent = await db.scalar(
        select(ReportEntitlement.id).where(
            ReportEntitlement.user_id == user.id, ReportEntitlement.resource_type == rtype,
            ReportEntitlement.resource_id == rid, ReportEntitlement.expires_at > now,
        ).limit(1)
    )
    return ent is not None
