import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import admin_user
from app.core.config import settings
from app.core.errors import AppError, NotFound
from app.db.session import get_db
from app.models.platform import (
    AIReport, AIStatus, IngestionJob, LeadStatus, ReportRequest, Role, Subscription, User,
)
from app.models.political import AgendaAnalysis, PromiseTracking
from app.schemas.admin import (
    AIGenerateIn, AIReportAdminOut, AIReviewIn, ContentReviewIn, GrantSubscriptionIn, IngestionJobOut,
    IngestTriggerIn, LeadPatchIn, UserPatchIn,
)
from app.schemas.auth import UserOut
from app.services.audit import audit
from app.services.ingestion.profiles import PROFILES

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(admin_user)])

_ALLOWED = {".xlsx", ".xlsm", ".csv"}  # PDFs: convert tables to CSV/XLSX first (see README)


def _upload_root() -> Path:
    p = Path(settings.upload_dir).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


async def _enqueue(request: Request, fn: str, *args) -> None:
    pool = getattr(request.app.state, "arq", None)
    if pool is None:
        raise AppError("Job queue unavailable (Redis not connected).")
    await pool.enqueue_job(fn, *args)


# ---------- ingestion ----------
@router.post("/ingestion/upload", response_model=IngestionJobOut, status_code=202)
async def upload_report(request: Request, file: UploadFile = File(...), source: str = Form(...), profile: str = Form(...),
                        election_id: int = Form(...), admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    """Upload an ECI statistical report / Lok Dhaba CSV / MyNeta CSV and queue parsing."""
    if source not in ("eci", "lokdhaba", "myneta") or profile not in PROFILES:
        raise AppError("Unknown source or profile.")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED:
        raise AppError(f"Unsupported file type {ext}. Allowed: {sorted(_ALLOWED)}")
    dest = _upload_root() / f"{uuid.uuid4().hex}{ext}"
    size, head = 0, b""
    with dest.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            head = head or chunk[:4]
            size += len(chunk)
            if size > settings.max_upload_mb * 1024 * 1024:
                out.close(); dest.unlink(missing_ok=True)
                raise AppError("File too large.")
            out.write(chunk)
    if ext in (".xlsx", ".xlsm") and head != b"PK\x03\x04":  # xlsx is a zip container
        dest.unlink(missing_ok=True)
        raise AppError("File content does not look like a valid .xlsx workbook.")
    job = IngestionJob(source=source, profile=profile, file_path=str(dest), election_id=election_id, created_by_id=admin.id)
    db.add(job)
    await db.flush()
    await db.commit()  # worker must see the row before it runs
    await audit("admin_upload", user_id=admin.id, request=request, resource_type="ingestion_job", resource_id=job.id,
                meta={"filename": re.sub(r"[^\w.\-]", "_", file.filename or ""), "size": size})
    await _enqueue(request, "run_ingestion", job.id)
    return job


@router.post("/ingestion/trigger", response_model=IngestionJobOut, status_code=202)
async def trigger_ingestion(body: IngestTriggerIn, request: Request, admin: User = Depends(admin_user),
                            db: AsyncSession = Depends(get_db)):
    """Queue a load from a file ALREADY on the server under UPLOAD_DIR (e.g. a Lok Dhaba CSV you downloaded).
    This platform does not scrape websites; fetch datasets per each source's terms, then point at the file."""
    path = Path(body.server_file_path).resolve()
    if _upload_root() not in path.parents or not path.is_file():
        raise AppError("server_file_path must be an existing file inside UPLOAD_DIR.")
    if body.profile not in PROFILES:
        raise AppError("Unknown profile.")
    job = IngestionJob(source=body.source, profile=body.profile, file_path=str(path), election_id=body.election_id, created_by_id=admin.id)
    db.add(job)
    await db.flush()
    await db.commit()
    await audit("admin_ingest_trigger", user_id=admin.id, request=request, resource_type="ingestion_job", resource_id=job.id)
    await _enqueue(request, "run_ingestion", job.id)
    return job


@router.get("/ingestion/jobs", response_model=list[IngestionJobOut])
async def list_jobs(db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(IngestionJob).order_by(IngestionJob.id.desc()).limit(100))).all()


# ---------- users & subscriptions ----------
@router.get("/users", response_model=list[UserOut])
async def list_users(db: AsyncSession = Depends(get_db), limit: int = 100, offset: int = 0):
    return (await db.scalars(select(User).order_by(User.id).limit(min(limit, 500)).offset(offset))).all()


@router.patch("/users/{user_id}", response_model=UserOut)
async def patch_user(user_id: int, body: UserPatchIn, request: Request, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    u = await db.get(User, user_id)
    if not u:
        raise NotFound("User not found")
    if body.role is not None:
        u.role = body.role
    if body.is_active is not None:
        u.is_active = body.is_active
        if not body.is_active:
            u.token_version += 1
    await audit("admin_user_patch", user_id=admin.id, request=request, resource_type="user", resource_id=user_id, meta=body.model_dump(mode="json"))
    return u


@router.post("/users/{user_id}/subscriptions", status_code=201)
async def grant_subscription(user_id: int, body: GrantSubscriptionIn, request: Request, admin: User = Depends(admin_user),
                             db: AsyncSession = Depends(get_db)):
    u = await db.get(User, user_id)
    if not u:
        raise NotFound("User not found")
    now = datetime.now(timezone.utc)
    sub = Subscription(user_id=user_id, plan=body.plan, starts_at=now, ends_at=now + timedelta(days=body.days), granted_by_admin_id=admin.id)
    db.add(sub)
    if u.role == Role.PUBLIC:
        u.role = Role.PAID
    await db.flush()
    await audit("admin_grant_subscription", user_id=admin.id, request=request, resource_type="user", resource_id=user_id, meta={"days": body.days})
    return {"subscription_id": sub.id, "ends_at": sub.ends_at}


# ---------- leads ----------
@router.get("/report-requests")
async def list_leads(status: LeadStatus | None = None, db: AsyncSession = Depends(get_db)):
    q = select(ReportRequest).order_by(ReportRequest.id.desc()).limit(200)
    if status:
        q = q.where(ReportRequest.status == status)
    return (await db.scalars(q)).all()


@router.patch("/report-requests/{lead_id}")
async def patch_lead(lead_id: int, body: LeadPatchIn, db: AsyncSession = Depends(get_db)):
    lead = await db.get(ReportRequest, lead_id)
    if not lead:
        raise NotFound("Lead not found")
    if body.status is not None:
        lead.status = body.status
    if body.admin_notes is not None:
        lead.admin_notes = body.admin_notes
    return lead


# ---------- AI review workflow ----------
@router.post("/ai/generate", status_code=202)
async def generate_ai(body: AIGenerateIn, request: Request, admin: User = Depends(admin_user)):
    if not (body.candidate_id or body.constituency_id):
        raise AppError("Provide candidate_id or constituency_id.")
    await _enqueue(request, "run_ai_generation", body.kind.value, body.candidate_id, body.constituency_id, admin.id)
    return {"queued": True, "note": "Output is saved as a DRAFT and must be published after review."}


@router.get("/ai/reports", response_model=list[AIReportAdminOut])
async def list_ai(status: AIStatus = AIStatus.DRAFT, db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(AIReport).where(AIReport.status == status).order_by(AIReport.id.desc()).limit(100))).all()


@router.post("/ai/reports/{report_id}/review", response_model=AIReportAdminOut)
async def review_ai(report_id: int, body: AIReviewIn, request: Request, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    r = await db.get(AIReport, report_id)
    if not r:
        raise NotFound("Report not found")
    if body.action == "publish":
        if body.edited_content is not None:
            r.content = body.edited_content
        if r.content is None:
            raise AppError("Cannot publish a report whose output was not valid JSON; supply edited_content.")
        r.status = AIStatus.PUBLISHED
    else:
        r.status = AIStatus.REJECTED
    r.reviewed_by_id, r.reviewed_at, r.review_notes = admin.id, datetime.now(timezone.utc), body.notes
    await audit("ai_review", user_id=admin.id, request=request, resource_type="ai_report", resource_id=report_id, meta={"action": body.action})
    return r


# ---------- manual content review (promises / agenda) ----------
@router.patch("/promises/{promise_id}/review")
async def review_promise(promise_id: int, body: ContentReviewIn, db: AsyncSession = Depends(get_db)):
    p = await db.get(PromiseTracking, promise_id)
    if not p:
        raise NotFound("Promise not found")
    p.review_status = body.review_status
    return {"id": p.id, "review_status": p.review_status}


@router.patch("/agenda/{agenda_id}/review")
async def review_agenda(agenda_id: int, body: ContentReviewIn, db: AsyncSession = Depends(get_db)):
    a = await db.get(AgendaAnalysis, agenda_id)
    if not a:
        raise NotFound("Agenda analysis not found")
    a.review_status = body.review_status
    return {"id": a.id, "review_status": a.review_status}
