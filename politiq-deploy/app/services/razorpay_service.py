import hashlib
import hmac

import razorpay
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.errors import AppError


class PaymentConfigError(AppError):
    status_code, code = 503, "payments_unavailable"


def _client() -> razorpay.Client:
    if not (settings.razorpay_key_id and settings.razorpay_key_secret):
        raise PaymentConfigError("Payments are not configured.")
    return razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))


async def create_order(amount_paise: int, receipt: str, notes: dict) -> dict:
    client = _client()
    return await run_in_threadpool(
        client.order.create,
        {"amount": amount_paise, "currency": "INR", "receipt": receipt[:40], "notes": notes, "payment_capture": 1},
    )


def _hmac(secret: str, msg: bytes) -> str:
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def verify_checkout_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """Razorpay checkout signature = HMAC_SHA256(order_id|payment_id, key_secret)."""
    expected = _hmac(settings.razorpay_key_secret, f"{order_id}|{payment_id}".encode())
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    if not settings.razorpay_webhook_secret:
        return False
    return hmac.compare_digest(_hmac(settings.razorpay_webhook_secret, raw_body), signature)
