import logging

from fastapi import Request

from app.db.session import SessionLocal
from app.models.platform import AuditLog

log = logging.getLogger(__name__)


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else None)


async def audit(action: str, *, user_id: int | None, request: Request | None = None,
                resource_type: str | None = None, resource_id: int | str | None = None, meta: dict | None = None) -> None:
    """Writes in its OWN session/transaction so denials and errors are still recorded."""
    try:
        async with SessionLocal() as s:
            s.add(AuditLog(
                user_id=user_id, action=action, resource_type=resource_type,
                resource_id=str(resource_id) if resource_id is not None else None,
                ip=client_ip(request),
                user_agent=(request.headers.get("user-agent", "")[:300] if request else None),
                meta=meta,
            ))
            await s.commit()
    except Exception:  # noqa: BLE001  - auditing must never break the request path
        log.exception("failed to write audit log")
