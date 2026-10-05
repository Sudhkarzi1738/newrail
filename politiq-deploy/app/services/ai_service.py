import json
import logging
import re
from decimal import Decimal
from datetime import date, datetime
from uuid import UUID

from anthropic import AsyncAnthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompts import PROMPT_VERSION, SYSTEM_BASE, TEMPLATES
from app.core.config import AI_DISCLAIMER, settings
from app.core.errors import AppError, NotFound
from app.models.platform import AIKind, AIReport, AIStatus
from app.models.political import AgendaAnalysis, PromiseTracking, ReviewStatus
from app.services import queries

log = logging.getLogger(__name__)


class AINotConfigured(AppError):
    status_code, code = 503, "ai_unavailable"


def _json_default(o):
    if isinstance(o, (Decimal,)):
        return float(o)
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if isinstance(o, UUID):
        return str(o)
    if hasattr(o, "value"):
        return o.value
    raise TypeError(type(o))


def _to_jsonable(d: dict) -> dict:
    return json.loads(json.dumps(d, default=_json_default))


async def build_context(db: AsyncSession, kind: AIKind, candidate_id: int | None, constituency_id: int | None) -> dict:
    if kind == AIKind.PROMISE_ANALYSIS:
        career = await queries.load_career(db, candidate_id or 0)
        if not career:
            raise NotFound("Candidate not found")
        promises = (await db.scalars(select(PromiseTracking).where(PromiseTracking.candidate_id == candidate_id))).all()
        if not promises:
            raise AppError("No promises loaded for this candidate; nothing to analyse.")
        return {"candidate": career["name"], "promises": [
            {"promise_id": p.id, "promise_text": p.promise_text, "source": p.source,
             "evidence": p.evidence, "evidence_urls": p.evidence_urls} for p in promises]}

    if kind == AIKind.AGENDA_SUMMARY:
        career = await queries.load_career(db, candidate_id or 0)
        if not career:
            raise NotFound("Candidate not found")
        ag = (await db.scalars(select(AgendaAnalysis).where(AgendaAnalysis.candidate_id == candidate_id)
                               .order_by(AgendaAnalysis.id.desc()).limit(1))).first()
        if not ag or not ag.raw_items:
            raise AppError("No raw agenda items loaded for this candidate.")
        return {"candidate": career["name"], "term": ag.term_label, "questions_raised": ag.questions_raised,
                "debates_participated": ag.debates_participated, "raw_items": ag.raw_items}

    # OPPOSITION_STRATEGY
    hist = await queries.load_constituency_history(db, constituency_id or 0)
    if not hist or not hist["history"]:
        raise AppError("No election results loaded for this constituency.")
    ctx: dict = {"constituency_history": hist}
    latest = hist["history"][0]
    winner = next((c for c in latest["candidates"] if c["position"] == 1), None)
    if winner:
        career = await queries.load_career(db, winner["candidate_id"])
        promises = (await db.scalars(select(PromiseTracking).where(
            PromiseTracking.candidate_id == winner["candidate_id"],
            PromiseTracking.review_status == ReviewStatus.APPROVED))).all()
        ctx["incumbent"] = {"career": career, "approved_promises": [
            {"text": p.promise_text, "status": p.status.value, "evidence": p.evidence} for p in promises]}
    return ctx


def _parse_json(text: str) -> dict | None:
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        out = json.loads(t)
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        return None


async def generate_report(db: AsyncSession, kind: AIKind, candidate_id: int | None,
                          constituency_id: int | None, created_by_id: int | None) -> AIReport:
    if not settings.anthropic_api_key:
        raise AINotConfigured("ANTHROPIC_API_KEY is not set.")
    ctx = _to_jsonable(await build_context(db, kind, candidate_id, constituency_id))
    prompt = TEMPLATES[kind.value].replace("{{CONTEXT}}", json.dumps(ctx, ensure_ascii=False, indent=1))

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    resp = await client.messages.create(
        model=settings.anthropic_model, max_tokens=4000, temperature=0.2,
        system=SYSTEM_BASE, messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    parsed = _parse_json(text)
    if parsed is None:
        log.warning("AI output was not valid JSON (kind=%s)", kind.value)

    report = AIReport(
        kind=kind, candidate_id=candidate_id, constituency_id=constituency_id, status=AIStatus.DRAFT,
        content=parsed, content_text=None if parsed else text, input_snapshot=ctx,
        model=settings.anthropic_model, prompt_version=PROMPT_VERSION, disclaimer=AI_DISCLAIMER,
        input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens, created_by_id=created_by_id,
    )
    db.add(report)
    await db.flush()
    return report
