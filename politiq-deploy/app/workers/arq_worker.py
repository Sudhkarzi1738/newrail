"""Run:  arq app.workers.arq_worker.WorkerSettings"""
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.logging import setup_logging
from app.workers.tasks import run_ai_generation, run_ingestion


async def startup(ctx: dict) -> None:
    setup_logging()


class WorkerSettings:
    functions = [run_ingestion, run_ai_generation]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 4
    job_timeout = 3600
    max_tries = 2
