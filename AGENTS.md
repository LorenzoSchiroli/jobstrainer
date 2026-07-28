# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Project Overview

**jobstrainer** is a job search ranking system. It scrapes job offers from multiple sources, enriches them with LLM-parsed metadata and dense embeddings, stores them in Postgres + OpenSearch, and serves a hybrid BM25 + k-NN search endpoint with cross-encoder reranking.

## Repository Structure

This is a `uv` workspace with two packages:

- **`backend/`** — FastAPI service: REST API (JWT auth), Postgres (SQLAlchemy async), OpenSearch hybrid search, outbox reconcile worker, LangGraph agents (advanced search, tailorer)
- **`ingestion/`** — Pipeline: job scraping, LLM-based offer parsing, company enrichment, embedding, and HTTP posting to backend

Other top-level directories:
- `frontend/` — React (Vite) SPA, served by nginx in Docker/k8s
- `extension/` — Chrome extension (Tailorer side panel; calls the backend directly)
- `deploy/` — Helm chart (`deploy/helm/jobstrainer/`) + k8s runbook (`deploy/k8s/README.md`)
- `tailor/` — standalone CV-tailoring scripts (`tailor/tailor_cv.py`; `python -m tailor` generates a cover letter)

Ad-hoc CLIs (run from `ingestion/`):
- `uv run python -m ingestion.offer "<query>"` — offer scraping
- `uv run python -m ingestion.company "<name>"` — company enrichment

## Commands

### Infrastructure

Kubernetes (Helm, kind cluster locally) is the canonical deployment; docker-compose still works but is being phased out.

```bash
docker compose up -d postgres opensearch   # start dependencies only
docker compose up --build                  # full stack (postgres + opensearch + backend + ingestion + frontend)

# Kubernetes — full runbook (cluster/images/secret setup) in deploy/k8s/README.md
helm install jobstrainer deploy/helm/jobstrainer -f deploy/helm/jobstrainer/values-local.yaml
```

The chart deploys the whole stack: postgres, opensearch, api (+ HPA), worker, ingestion CronJob, frontend, and a bootstrap hook Job (migrations + OpenSearch index + checkpointer setup). It references a pre-created `jobstrainer-secrets` secret. `deploy/k8s/loadtest-job.yaml` is an in-cluster k6 load-test Job for the HPA demo.

### Hetzner ARM64 deployment gate

Before deploying the Hetzner profile, build backend, ingestion, and frontend
with `docker buildx build --platform linux/arm64`. The backend image includes
`pg_dump` and `rclone` for the worker's nightly Postgres backup loop.
The ingestion image is the highest-risk component because it includes
Playwright and python-jobspy/tls-client. If the ARM64 gate fails, do not deploy
under emulation; switch the infrastructure profile to x86 and revisit the
budget.

### Backend

```bash
cd backend
uv run alembic upgrade head                # apply DB migrations
uv run uvicorn backend.main:app --reload   # run dev server on :8000
uv run pytest                              # run all backend tests
uv run pytest tests/test_jobs.py           # run a single test file
uv run pytest tests/search/test_filters.py::test_build_clauses_empty_when_all_none  # single test
```

Tests require a live Postgres at `postgresql+asyncpg://postgres:postgres@localhost:5432/jobstrainer_test` (override via `TEST_DATABASE_URL`). OpenSearch and ML models are mocked in the test suite.

### Ingestion

```bash
cd ingestion
uv run python -m ingestion.pipeline "machine learning engineer" --hours 48
uv run pytest                              # run all ingestion tests
```

### Required Environment Variables

Create a `.env` file (see `.env.example`):

```
GROQ_API_KEY=...
GROQ_MODEL_LARGE=...                    # advanced search, tailorer + cover letter generation
GROQ_MODEL_BASE=...                     # offer/company parsing
SECRET_KEY=...                          # JWT signing
ACCESS_TOKEN_EXPIRE_DAYS=7
OFFER_QUERY=...                         # used by the ingestion Docker service / CronJob
SERPERDEV_API_KEY=...                   # company enrichment web search
ADZUNA_APP_ID=...                       # optional job source
ADZUNA_APP_KEY=...
DDGS_PROXY=...                          # optional proxy for DuckDuckGo scraping
```

Keep values UNQUOTED: `kubectl create secret --from-env-file` stores quotes verbatim (unlike dotenv), so a quoted `GROQ_API_KEY` yields Groq `401 invalid_api_key` in k8s.

## Architecture

### Search Pipeline (backend)

`POST /jobs/search` (JWT-protected, body `{query}`) runs four sequential steps —
**no LLM involved**:

1. **Query parsing** — deterministic regex parsing extracts `SearchFilters`
   (seniority, location_type, languages, etc.) and a `semantic_query` from the
   query text (`search/query_parsing.py`). The LLM-based
   `search/query_understanding.py` is used only by the separate advanced-search
   endpoint (`POST /jobs/search/advanced`, `search/advanced/`), which is
   work-in-progress.
2. **Hybrid retrieval** — OpenSearch hybrid query: BM25 on `description` + k-NN on `embedding` (384-dim, `BAAI/bge-small-en-v1.5`), results combined via min-max normalization with 50/50 weights (`search/retrieval.py`). Filter clauses are soft by default (scored `should` with boost=2) so near-misses still surface; words like "strictly" / "exactly" / "no exceptions" in the query set `SearchFilters.strict`, applying them as a hard `post_filter` with a larger prefetch (200).
3. **Cross-encoder reranking** — `cross-encoder/ms-marco-MiniLM-L-6-v2` reranks retrieved hits on `summary_text`, returns top 20 (`search/reranker.py`)
4. **Postgres round-trip** — full `Job` + `Company` records fetched by ID for the response

**Auth**: `backend/auth/` + `routers/auth.py` — JWT bearer tokens (`POST /auth/register`, `POST /auth/login`, `GET /auth/me`); most endpoints depend on `get_current_user`.

**Advanced search (WIP)** — `POST /jobs/search/advanced` (`routers/search_advanced.py`, `search/advanced/`): a Postgres-checkpointed LangGraph agent that uses the Groq LLM and per-user preference memory. It interrupts with up to 2 clarifying questions (answered via `POST /jobs/search/advanced/resume`), can critique/refine its retrieval, and returns fit-scored results. Requires an uploaded CV (`ApplicantProfile`).

### Backend Processes & Outbox Pattern

Three entrypoints (split for k8s):
- `backend.main:app` — API only; lifespan loads ML models, ensures the OpenSearch index/pipeline, and opens a LangGraph `AsyncPostgresSaver` checkpointer. No background sync tasks.
- `python -m backend.worker` — runs `reconcile_worker` + `retention_worker` from `outbox/worker.py` and `backup_worker` from `backup.py` (singleton Deployment in k8s)
- `python -m backend.bootstrap` — one-time setup: checkpointer tables + OpenSearch `created_at` backfill (the k8s bootstrap Job runs `alembic upgrade head` first)

Jobs and companies are written atomically to Postgres with an `outbox` row. Every 5 minutes `reconcile` bulk re-indexes to OpenSearch: jobs with unprocessed outbox rows plus live jobs (≤30 days old) missing from the index; `company_upserted` events patch company-derived fields on that company's job docs via `update_by_query()`. Every 6 hours `retention_worker` deletes OpenSearch docs older than 30 days. When `BACKUP_SBOX_*` is set, `backup_worker` runs a daily `pg_dump` + rclone upload to a Hetzner Storage Box (7-day rolling retention).

### Ingestion Pipeline

`ingestion/pipeline/__main__.py` runs end-to-end (`--hours` defaults to 72):
1. Scrape job offers from sources (jobspy, adzuna, arbeitnow, remotive) via `ingestion.offer.scraping`
2. Fetch full description if missing (requests + trafilatura; Playwright is used only by company-page scraping)
3. LLM-parse each offer with Groq → `OfferSummary` (role_info, requirements, responsibilities, domain)
4. Embed: `title + summary_text` → 384-dim vector via `BAAI/bge-small-en-v1.5`
5. POST jobs and companies to backend REST API; enrich companies whose profile is mostly empty (≥ half fields null)

### Data Models

- **`Company`** — unique by `name`; enriched with employee_count, founded_year, review_score, financial_health_score (int 0-10), is_consulting, is_startup, industry, country
- **`Job`** — unique by `url`; stores parsed fields (employment_type, location_type, seniority, languages_required) and `summary` JSONB
- **`Outbox`** — transient sync table; `processed_at` is NULL until worker drains it
- **`User`** (`models.py`), **`ApplicantProfile`** / **`Application`** (`tailorer/models.py`) — auth accounts and per-user CV/profile data

### OpenSearch Index (`jobs`)

Embedding dimension: 384. HNSW with cosine similarity via Lucene engine. Hybrid pipeline name: `hybrid-pipeline` (configured at startup via `PUT /_search/pipeline`).

### DB Migrations

Alembic is in `backend/alembic/`. Add schema changes there; the compose backend container runs `alembic upgrade head` at startup, and in k8s the bootstrap hook Job runs it before rollout.

## Key Dependencies

| Component | Library |
|-----------|---------|
| API framework | FastAPI + uvicorn |
| ORM / async DB | SQLAlchemy async + asyncpg |
| Vector search | opensearch-py[async] |
| Bi-encoder (embed) | sentence-transformers (`BAAI/bge-small-en-v1.5`) |
| Cross-encoder (rerank) | sentence-transformers (`cross-encoder/ms-marco-MiniLM-L-6-v2`) |
| LLM | Groq SDK; agents use `langchain-openai` `ChatOpenAI` pointed at Groq's OpenAI-compatible API |
| Agents / checkpointing | LangGraph + `langgraph-checkpoint-postgres` (advanced search, tailorer) |
| Auth | python-jose (JWT) + passlib[bcrypt] |
| Scraping | python-jobspy, Playwright, trafilatura, ddgs |
| Package manager | uv workspace |
