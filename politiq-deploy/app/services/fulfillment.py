"""Idempotent post-payment unlocking. Called from BOTH /payments/verify and the webhook; whichever
arrives first does the work, the other is a no-op (guarded by a row lock + fulfilled_at)."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.platform import (
    LeadStatus, Payment, PaymentStatus, Product, ReportEntitlement, ReportRequest, Role, Subscription, User,
)


async def mark_paid_and_fulfill(db: AsyncSession, razorpay_order_id: str, razorpay_payment_id: str) -> bool:
    pay = await db.scalar(select(Payment).where(Payment.razorpay_order_id == razorpay_order_id).with_for_update())
    if pay is None:
        return False
    if pay.fulfilled_at is not None:
        return True  # already done
    now = datetime.now(timezone.utc)
    pay.status = PaymentStatus.PAID
    pay.razorpay_payment_id = razorpay_payment_id

    if pay.product == Product.SUBSCRIPTION_MONTHLY:
        # extend from the current end if the user already has a live subscription
        latest_end = await db.scalar(
            select(Subscription.ends_at).where(Subscription.user_id == pay.user_id, Subscription.ends_at > now)
            .order_by(Subscription.ends_at.desc()).limit(1)
        )
        start = latest_end or now
        db.add(Subscription(user_id=pay.user_id, plan="monthly", starts_at=now,
                            ends_at=start + timedelta(days=settings.subscription_days), payment_id=pay.id))
    elif pay.product == Product.REPORT_UNLOCK and pay.resource_type and pay.resource_id:
        db.add(ReportEntitlement(
            user_id=pay.user_id, resource_type=pay.resource_type, resource_id=pay.resource_id,
            expires_at=now + timedelta(days=settings.report_entitlement_days), payment_id=pay.id))

    user = await db.get(User, pay.user_id)
    if user and user.role == Role.PUBLIC:
        user.role = Role.PAID  # informational label; real access is still checked via has_access()
    if pay.report_request_id:
        lead = await db.get(ReportRequest, pay.report_request_id)
        if lead:
            lead.status = LeadStatus.PAID
    pay.fulfilled_at = now
    return True
