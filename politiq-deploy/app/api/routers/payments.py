import json
import logging

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, current_user_optional
from app.core.config import settings
from app.core.errors import AppError, Forbidden, NotFound
from app.core.rate_limit import RateLimiter
from app.db.session import get_db
from app.models.platform import (
    LeadStatus, Payment, PaymentStatus, Product, ReportRequest, ResourceType, User,
)
from app.schemas.billing import OrderIn, OrderOut, ReportRequestIn, ReportRequestOut, VerifyIn, VerifyOut
from app.services import razorpay_service as rz
from app.services.audit import audit
from app.services.fulfillment import mark_paid_and_fulfill

log = logging.getLogger(__name__)
limit = RateLimiter(lambda: 20, "billing")
router = APIRouter(tags=["billing"], dependencies=[Depends(limit)])


def _price(product: Product) -> int:
    # Amount is ALWAYS decided server-side; the client never sends a price.
    amt = {Product.REPORT_UNLOCK: settings.price_report_unlock_paise,
           Product.SUBSCRIPTION_MONTHLY: settings.price_subscription_monthly_paise}[product]
    if amt <= 0:
        raise AppError("This product is not available for online purchase yet. Please contact us.")
    return amt


async def _create_order(db: AsyncSession, user: User, body: OrderIn) -> OrderOut:
    if body.product == Product.REPORT_UNLOCK and not (body.resource_type and body.resource_id):
        raise AppError("resource_type and resource_id are required for report_unlock")
    if body.report_request_id:
        lead = await db.get(ReportRequest, body.report_request_id)
        if not lead or lead.user_id not in (None, user.id):
            raise Forbidden("Not your report request")
    amount = _price(body.product)
    order = await rz.create_order(amount, f"u{user.id}", {"user_id": str(user.id), "product": body.product.value})
    pay = Payment(user_id=user.id, product=body.product, resource_type=body.resource_type, resource_id=body.resource_id,
                  report_request_id=body.report_request_id, amount_paise=amount, razorpay_order_id=order["id"])
    db.add(pay)
    await db.flush()
    return OrderOut(payment_id=pay.id, razorpay_order_id=order["id"], amount_paise=amount, currency="INR",
                    razorpay_key_id=settings.razorpay_key_id)


@router.post("/report-requests", response_model=ReportRequestOut, status_code=201)
async def create_report_request(body: ReportRequestIn, request: Request, user: User | None = Depends(current_user_optional),
                                db: AsyncSession = Depends(get_db)):
    """'Request Full Report' lead. Open to anonymous visitors; if logged in and create_order=true,
    also returns a Razorpay order so the front end can open checkout immediately."""
    lead = ReportRequest(user_id=user.id if user else None, name=body.name, email=body.email.lower(), phone=body.phone,
                         organization=body.organization, candidate_id=body.candidate_id,
                         constituency_id=body.constituency_id, request_type=body.request_type, message=body.message)
    db.add(lead)
    await db.flush()
    await audit("report_request", user_id=user.id if user else None, request=request, resource_type="report_request", resource_id=lead.id)
    order = None
    if body.create_order and user:
        rtype, rid = ((ResourceType.CANDIDATE, body.candidate_id) if body.candidate_id
                      else (ResourceType.CONSTITUENCY, body.constituency_id))
        if rid:
            order = await _create_order(db, user, OrderIn(product=Product.REPORT_UNLOCK, resource_type=rtype,
                                                          resource_id=rid, report_request_id=lead.id))
            lead.status = LeadStatus.AWAITING_PAYMENT
    return ReportRequestOut(id=lead.id, status=lead.status, order=order)


@router.post("/payments/orders", response_model=OrderOut, status_code=201)
async def create_order(body: OrderIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await _create_order(db, user, body)


@router.post("/payments/verify", response_model=VerifyOut)
async def verify(body: VerifyIn, request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Called by the front end after Razorpay checkout succeeds. Verifies the HMAC signature, then unlocks."""
    pay = await db.scalar(select(Payment).where(Payment.razorpay_order_id == body.razorpay_order_id, Payment.user_id == user.id))
    if not pay:
        raise NotFound("Order not found")
    if not rz.verify_checkout_signature(body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature):
        pay.status = PaymentStatus.FAILED
        await audit("payment_signature_invalid", user_id=user.id, request=request, resource_type="payment", resource_id=pay.id)
        await db.commit()  # persist FAILED before raising
        raise AppError("Payment signature verification failed.")
    ok = await mark_paid_and_fulfill(db, body.razorpay_order_id, body.razorpay_payment_id)
    await audit("payment_verified", user_id=user.id, request=request, resource_type="payment", resource_id=pay.id)
    return VerifyOut(status="paid", fulfilled=ok)


@router.post("/payments/webhook", include_in_schema=False)
async def webhook(request: Request, x_razorpay_signature: str = Header(default=""), db: AsyncSession = Depends(get_db)):
    """Server-to-server source of truth (covers users who close the tab before /verify). Configure in the
    Razorpay dashboard for events: payment.captured, order.paid."""
    raw = await request.body()
    if not rz.verify_webhook_signature(raw, x_razorpay_signature):
        raise Forbidden("bad signature")
    event = json.loads(raw)
    if event.get("event") in ("payment.captured", "order.paid"):
        ent = event["payload"].get("payment", {}).get("entity", {})
        order_id, payment_id = ent.get("order_id"), ent.get("id")
        if order_id and payment_id:
            await mark_paid_and_fulfill(db, order_id, payment_id)
    return {"ok": True}
