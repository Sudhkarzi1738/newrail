"""PAID endpoints. Every route declares require_paid(...) so entitlement is verified BEFORE any paid query runs."""
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_paid
from app.core.config import AI_DISCLAIMER, settings
from app.core.errors import NotFound
from app.core.rate_limit import RateLimiter
from app.db.session import get_db
from app.models.platform import AIKind, AIReport, AIStatus, ResourceType, User
from app.models.political import AgendaAnalysis, PromiseTracking, ReviewStatus
from app.schemas.data import AgendaOut, AIReportOut, CareerOut, DetailedResultOut, PromiseOut
from app.services import queries, reports
from app.services.audit import audit

paid_limit = RateLimiter(lambda: settings.rate_limit_paid_per_min, "paid")
router = APIRouter(prefix="/paid", tags=["paid"], dependencies=[Depends(paid_limit)])

cand_guard = require_paid(ResourceType.CANDIDATE, "candidate_id")
cons_guard = require_paid(ResourceType.CONSTITUENCY, "constituency_id")


@router.get("/candidates/{candidate_id}/career", response_model=CareerOut)
async def career(candidate_id: int, _: User = Depends(cand_guard), db: AsyncSession = Depends(get_db)):
    data = await queries.load_career(db, candidate_id)
    if not data:
        raise NotFound("Candidate not found")
    return data


@router.get("/constituencies/{constituency_id}/elections/{election_id}/results", response_model=DetailedResultOut)
async def detailed_results(constituency_id: int, election_id: int, _: User = Depends(cons_guard),
                           db: AsyncSession = Depends(get_db)):
    data = await queries.load_results(db, constituency_id, election_id)
    if not data:
        raise NotFound("No results found")
    return data


@router.get("/candidates/{candidate_id}/promises", response_model=list[PromiseOut])
async def promises(candidate_id: int, _: User = Depends(cand_guard), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(PromiseTracking).where(
        PromiseTracking.candidate_id == candidate_id, PromiseTracking.review_status == ReviewStatus.APPROVED))).all()
    return [PromiseOut.model_validate(p).model_copy(update={"disclaimer": AI_DISCLAIMER if p.ai_suggested else None})
            for p in rows]


@router.get("/candidates/{candidate_id}/agenda", response_model=list[AgendaOut])
async def agenda(candidate_id: int, _: User = Depends(cand_guard), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(AgendaAnalysis).where(
        AgendaAnalysis.candidate_id == candidate_id, AgendaAnalysis.review_status == ReviewStatus.APPROVED))).all()
    return [AgendaOut.model_validate(a).model_copy(update={"disclaimer": AI_DISCLAIMER if a.ai_summary else None})
            for a in rows]


async def _published_ai(db: AsyncSession, kind: AIKind, *, candidate_id=None, constituency_id=None) -> list[AIReport]:
    q = select(AIReport).where(AIReport.kind == kind, AIReport.status == AIStatus.PUBLISHED)
    if candidate_id:
        q = q.where(AIReport.candidate_id == candidate_id)
    if constituency_id:
        q = q.where(AIReport.constituency_id == constituency_id)
    return list((await db.scalars(q.order_by(AIReport.id.desc()).limit(1))).all())


@router.get("/constituencies/{constituency_id}/opposition-brief", response_model=AIReportOut)
async def opposition_brief(constituency_id: int, _: User = Depends(cons_guard), db: AsyncSession = Depends(get_db)):
    """Only ADMIN-PUBLISHED briefs are served; drafts are never exposed."""
    r = await _published_ai(db, AIKind.OPPOSITION_STRATEGY, constituency_id=constituency_id)
    if not r:
        raise NotFound("No reviewed brief yet for this constituency. Our team can prepare one - request a report.")
    return r[0]


@router.get("/candidates/{candidate_id}/export")
async def export(candidate_id: int, request: Request, fmt: Literal["xlsx", "pdf"] = Query("xlsx", alias="format"),
                 user: User = Depends(cand_guard), db: AsyncSession = Depends(get_db)):
    data = await queries.load_career(db, candidate_id)
    if not data:
        raise NotFound("Candidate not found")
    ai = []
    for kind in (AIKind.PROMISE_ANALYSIS, AIKind.AGENDA_SUMMARY):
        for r in await _published_ai(db, kind, candidate_id=candidate_id):
            ai.append({"kind": kind.value, "content": r.content, "content_text": r.content_text})
    await audit("export", user_id=user.id, request=request, resource_type="candidate", resource_id=candidate_id, meta={"format": fmt})
    if fmt == "xlsx":
        body, mt = reports.candidate_xlsx(data, ai), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        body, mt = reports.candidate_pdf(data, ai), "application/pdf"
    return Response(body, media_type=mt, headers={
        "Content-Disposition": f'attachment; filename="candidate_{candidate_id}.{fmt}"', "Cache-Control": "private, no-store"})
