# PolitIQ - Indian Political Consultancy Platform (backend)

FastAPI + SQLAlchemy 2.0 (async) + Alembic + PostgreSQL 15+, Redis, ARQ workers, Razorpay, Anthropic Claude.

**This repository contains no election data.** There are no seeded results, candidates or vote counts. Real data is
loaded from ECI / Lok Dhaba / MyNeta files via the ingestion pipeline (see "Loading real data").

## Project structure
```
app/
  main.py                  app factory, middleware (request-id, security headers), routers
  core/                    config (env), security (JWT/bcrypt), errors, rate_limit (Redis), logging (JSON)
  db/                      Base + naming conventions, async session
  models/
    political.py           State, Constituency, Party, Election, Candidate, CandidateElection,
                           Affidavit, PromiseTracking, AgendaAnalysis
    platform.py            User, Subscription, ReportEntitlement, Payment, ReportRequest,
                           AIReport, AuditLog, IngestionJob
  schemas/                 Pydantic v2 request/response models (auth, data, billing, admin)
  api/deps.py              auth + role + require_paid(...) paywall dependency
  api/routers/             auth, public, paid, payments (+ report-requests), admin
  services/
    access.py              has_access(): the single paywall decision
    fulfillment.py         idempotent unlock after payment
    razorpay_service.py    order creation + signature verification
    ai_service.py          context building from DB facts -> Claude -> DRAFT AIReport
    queries.py             shared read helpers
    reports.py             Excel / PDF export
    audit.py               AuditLog writer (own transaction)
    ingestion/             profiles (column maps), readers (xlsx/csv), loaders (upsert + derived stats)
  ai/prompts.py            Claude prompt templates (promise / opposition / agenda)
  workers/                 ARQ worker + tasks (ingestion, AI generation)
alembic/                   async migration env
scripts/create_admin.py
```

## Setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in secrets
docker compose up -d            # Postgres 16 + Redis (or use your own)
alembic revision --autogenerate -m "initial schema"   # first time only; review the generated file
alembic upgrade head
python -m scripts.create_admin admin@yourfirm.com 'a-strong-password'
uvicorn app.main:app --reload                 # API  -> http://localhost:8000/docs
arq app.workers.arq_worker.WorkerSettings     # worker (separate terminal)
```
Recommended after migrating (fast `ILIKE` search): `CREATE EXTENSION pg_trgm;` and trigram GIN indexes on
`candidates.normalized_name` and `constituencies.name`.

PostgreSQL **15+** is required (`UNIQUE ... NULLS NOT DISTINCT` on elections).

## Environment variables
| Var | Purpose |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@host/db` |
| `REDIS_URL` | rate limiting + ARQ queue |
| `JWT_SECRET` | long random string; rotate to invalidate all sessions |
| `ACCESS_TOKEN_MINUTES` / `REFRESH_TOKEN_DAYS` | token lifetimes (15 / 14) |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` | payments |
| `PRICE_REPORT_UNLOCK_PAISE`, `PRICE_SUBSCRIPTION_MONTHLY_PAISE` | **your** pricing, in paise; `0` disables checkout |
| `REPORT_ENTITLEMENT_DAYS`, `SUBSCRIPTION_DAYS` | validity windows |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | Claude analysis |
| `UPLOAD_DIR`, `MAX_UPLOAD_MB` | admin file uploads |
| `RATE_LIMIT_PUBLIC_PER_MIN`, `RATE_LIMIT_PAID_PER_MIN` | per-IP limits |
| `CORS_ORIGINS` | JSON list of allowed front-end origins |
| `APP_ENV` | `production` disables /docs and /openapi.json |

## How the paywall works
1. **Public** (`/api/v1/public/*`): search, recent elections, and *basic result* (winner, party, margin, vote %). Every
   basic result carries a `cta` pointing to `POST /api/v1/report-requests`. No opponents, history or analysis.
2. **Paid** (`/api/v1/paid/*`): each route declares `require_paid(ResourceType, "<path_param>")`. The dependency runs
   *before* the handler, so no paid query executes without entitlement. Access = admin, **or** a live `Subscription`, **or**
   an unexpired `ReportEntitlement` for that exact candidate/constituency. `Role.PAID` alone is a label, not a grant.
   Denials return **402** with a CTA payload and are audit-logged (`paid_denied`); grants are logged (`paid_access`, `export`).
3. **Lead -> payment**: `POST /report-requests` stores a `ReportRequest` lead (anonymous allowed). If the caller is logged in
   and sends `create_order: true`, a Razorpay order is returned for the one-time unlock. Prices are set server-side only.
4. **Unlock**: after checkout, the front end calls `POST /payments/verify` (HMAC-SHA256 of `order_id|payment_id` with your
   key secret). The Razorpay **webhook** (`payment.captured`, `order.paid`) is the backup. Both call
   `mark_paid_and_fulfill`, which row-locks the payment and is idempotent (`fulfilled_at`). It creates a `Subscription` or a
   `ReportEntitlement`, and moves the linked lead to `paid`.
5. **AI content**: Claude output is stored as a `DRAFT` `AIReport` with the exact input facts snapshot. Paid users only ever see
   `PUBLISHED` reports, after an admin reviews them (`POST /admin/ai/reports/{id}/review`). Every AI payload carries the
   disclaimer *"AI-assisted analysis - not official data."* Promises/agenda rows are served only when `review_status=approved`.

## Loading real data
1. Create the `Election` row (house, year, state or NULL for Lok Sabha) and seed `State` rows with official codes.
2. Get official files: ECI statistical reports (Excel), Lok Dhaba CSV exports, MyNeta/ADR exports, honouring each source's terms.
3. **Verify the header aliases** in `app/services/ingestion/profiles.py` against the real file. Aliases there are placeholders
   because layouts change between years. Add a new `Profile` per layout.
4. `POST /admin/ingestion/upload` (multipart: `file`, `source`, `profile`, `election_id`) queues parsing; check
   `GET /admin/ingestion/jobs` for stats and row errors. For files already on the server use `/admin/ingestion/trigger`.
5. After results load: position, winner, margin, vote share and deposit status are derived from vote counts (official
   values from the file are kept when present). Then load MyNeta affidavits (`source=myneta`, `profile=myneta_csv`).
6. Candidate identity: the loader auto-links a person across elections only on an unambiguous name + state match; everything
   else becomes a new `identity_verified=false` person for admin merge review. Wrong merges are worse than duplicates.
7. PDFs: convert tables to XLSX/CSV first (e.g. with a table-extraction tool), then upload. Promises and agenda items
   (`PromiseTracking`, `AgendaAnalysis.raw_items`) are entered by researchers or loaded from official records (Sansad, PRS).

## Security notes
- Short-lived access tokens; refresh tokens carry a `token_version`; logout / deactivation bumps it (revokes all tokens).
- Upload validation: extension allow-list, size cap, xlsx magic bytes, random server-side filenames, path-confined triggers.
- Audit log writes use a separate transaction so denials and failures are recorded.
- Paid/admin responses send `Cache-Control: private, no-store`. Put the API behind TLS and set `X-Forwarded-For` from a trusted proxy only.
- Run migrations and review the autogenerated revision before applying; add tests for `has_access` and payment idempotency before launch.

## Status
Code was written to be production-oriented but has **not been executed against a live database, Razorpay or Anthropic** in
this build environment (only syntax-checked). Expect to run it, add tests, and fix integration details.
