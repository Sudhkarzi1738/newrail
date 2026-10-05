import logging
import uuid
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.api.routers import admin, auth, paid, payments, public
from app.core.config import settings
from app.core.errors import register_handlers
from app.core.logging import request_id_ctx, setup_logging

setup_logging()
log = logging.getLogger("politiq")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        app.state.arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    except Exception:  # noqa: BLE001
        log.warning("ARQ pool unavailable; background jobs cannot be enqueued")
        app.state.arq = None
    yield
    await app.state.redis.aclose()
    if app.state.arq:
        await app.state.arq.aclose()


app = FastAPI(title="PolitIQ - Indian Political Consultancy API", version="0.1.0", lifespan=lifespan,
              docs_url=None if settings.app_env == "production" else "/docs",
              redoc_url=None, openapi_url=None if settings.app_env == "production" else "/openapi.json")
register_handlers(app)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["GET", "POST", "PATCH"], allow_headers=["Authorization", "Content-Type"])


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    request_id_ctx.set(rid)
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    response.headers["X-Content-Type-Options"] = "nosniff"
    if request.url.path.startswith(("/api/v1/paid", "/api/v1/admin")):
        response.headers["Cache-Control"] = "private, no-store"
    log.info("%s %s -> %s", request.method, request.url.path, response.status_code)
    return response


for r in (auth.router, public.router, paid.router, payments.router, admin.router):
    app.include_router(r, prefix="/api/v1")


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"ok": True}
