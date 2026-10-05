import logging
from pathlib import Path

from app.db.session import SessionLocal
from app.models.platform import AIKind, IngestionJob, JobStatus
from app.services import ai_service
from app.services.ingestion import loaders

log = logging.getLogger(__name__)


async def run_ingestion(ctx: dict, job_id: int) -> None:
    async with SessionLocal() as db:
        job = await db.get(IngestionJob, job_id)
        if not job:
            return
        job.status = JobStatus.RUNNING
        await db.commit()
        try:
            if job.election_id is None:
                raise ValueError("election_id is required")
            path = Path(job.file_path)
            if job.source == "myneta":
                stats = await loaders.load_affidavits(db, path, job.election_id)
            else:  # eci / lokdhaba
                stats = await loaders.load_results(db, path, job.profile, job.election_id)
            job.status, job.stats = JobStatus.DONE, stats
            await db.commit()
        except Exception as e:  # noqa: BLE001
            await db.rollback()
            job = await db.get(IngestionJob, job_id)
            job.status, job.error = JobStatus.FAILED, str(e)[:2000]
            await db.commit()
            log.exception("ingestion job %s failed", job_id)


async def run_ai_generation(ctx: dict, kind: str, candidate_id: int | None, constituency_id: int | None,
                            user_id: int | None) -> int:
    async with SessionLocal() as db:
        report = await ai_service.generate_report(db, AIKind(kind), candidate_id, constituency_id, user_id)
        await db.commit()
        return report.id
