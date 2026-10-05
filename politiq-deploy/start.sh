#!/bin/sh
set -e
# 1) create tables (safe to re-run). Switch to `alembic upgrade head` once you commit a migration.
python -m scripts.init_db
# 2) background worker (ingestion + AI jobs) in the same container so it shares the uploads disk
arq app.workers.arq_worker.WorkerSettings &
# 3) API
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
