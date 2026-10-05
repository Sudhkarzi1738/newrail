import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.logging import request_id_ctx

log = logging.getLogger(__name__)


class AppError(Exception):
    status_code = 400
    code = "app_error"

    def __init__(self, message: str, *, extra: dict | None = None):
        self.message, self.extra = message, extra or {}


class NotFound(AppError):
    status_code, code = 404, "not_found"


class Forbidden(AppError):
    status_code, code = 403, "forbidden"


class PaywallError(AppError):
    """402: content exists but caller has no entitlement. Carries the Request-Full-Report CTA."""

    status_code, code = 402, "payment_required"


def register_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_err(_: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.code, "message": exc.message, "request_id": request_id_ctx.get(), **exc.extra},
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": "Something went wrong.", "request_id": request_id_ctx.get()},
        )
