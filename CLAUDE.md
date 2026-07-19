# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**jobstrainer** is a job search ranking system. It scrapes job offers from multiple sources, enriches them with LLM-parsed metadata and dense embeddings, stores them in Postgres + OpenSearch, and serves a hybrid BM25 + k-NN search endpoint with cross-encoder reranking.

## Repository Structure

This is a `uv` workspace with two packages:

- **`backend/`** — FastAPI service: REST API, Postgres (SQLAlchemy async), OpenSearch hybrid search, outbox worker
- **`ingestion/`** — Pipeline: job scraping, LLM-based offer parsing, company enrichment, embedding, and HTTP posting to backend

Additional top-level scripts:
- `uv run python -m offer` — ad-hoc offer scraping CLI
- `uv run python -m company` — ad-hoc company enrichment CLI
- `tailor/tailor_cv.py` — CV tailoring script

## Commands

### Infrastructure

```bash
docker compose up -d postgres opensearch   # start dependencies only
docker compose up --build                  # full stack (postgres + opensearch + backend + ingestion)
```

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

Create a `.env` file (or export):

```
GROQ_API_KEY=...
GROQ_MODEL_LARGE=openai/gpt-oss-120b   # used by advanced search and cover letter generation
GROQ_MODEL_BASE=qwen/qwen3-32b         # used by offer/company parsing
OFFER_QUERY=...                         # used by the ingestion Docker service
SERPERDEV_API_KEY=...                   # company enrichment web search
ADZUNA_APP_ID=...                       # optional job source
ADZUNA_APP_KEY=...
DDGS_PROXY=...                          # optional proxy for DuckDuckGo scraping
```

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
2. **Hybrid retrieval** — OpenSearch hybrid query: BM25 on `description` + k-NN on `embedding` (384-dim, `BAAI/bge-small-en-v1.5`), results combined via min-max normalization with 50/50 weights (`search/retrieval.py`). Filter clauses are soft by default (scored `should` with boost=2) so near-misses still surface; pass `strict=true` in the request to apply them as a hard `post_filter` with a larger prefetch.
3. **Cross-encoder reranking** — `cross-encoder/ms-marco-MiniLM-L-6-v2` reranks retrieved hits on `summary_text`, returns top 20 (`search/reranker.py`)
4. **Postgres round-trip** — full `Job` + `Company` records fetched by ID for the response

### Outbox Pattern (backend)

Jobs and companies are written atomically to Postgres. A background `asyncio.Task` (`outbox/worker.py`) polls the `outbox` table every second and syncs to OpenSearch:
- `job_upserted` → `os_client.index()`
- `company_upserted` → `os_client.update_by_query()` (updates all jobs for that company)

### Ingestion Pipeline

`ingestion/pipeline/__init__.py` runs end-to-end:
1. Scrape job offers from sources (jobspy, adzuna, arbeitnow, remotive) via `ingestion.offer.scraping`
2. Fetch full description if missing (Playwright for JS-rendered pages, trafilatura for static)
3. LLM-parse each offer with Groq → `OfferSummary` (role_info, requirements, responsibilities, domain)
4. Embed: `title + summary_text` → 384-dim vector via `BAAI/bge-small-en-v1.5`
5. POST jobs and companies to backend REST API; trigger company enrichment for new/sparse companies

### Data Models

- **`Company`** — unique by `name`; enriched with size, funding, financial health (int 0-10), is_consulting, is_startup, industry, country
- **`Job`** — unique by `url`; stores parsed fields (employment_type, location_type, seniority, languages_required) and `summary` JSONB
- **`Outbox`** — transient sync table; `processed_at` is NULL until worker drains it

### OpenSearch Index (`jobs`)

Embedding dimension: 384. HNSW with cosine similarity via Lucene engine. Hybrid pipeline name: `hybrid-pipeline` (configured at startup via `PUT /_search/pipeline`).

### DB Migrations

Alembic is in `backend/alembic/`. Add schema changes there; the backend container runs `alembic upgrade head` at startup.

## Key Dependencies

| Component | Library |
|-----------|---------|
| API framework | FastAPI + uvicorn |
| ORM / async DB | SQLAlchemy async + asyncpg |
| Vector search | opensearch-py[async] |
| Bi-encoder (embed) | sentence-transformers (`BAAI/bge-small-en-v1.5`) |
| Cross-encoder (rerank) | sentence-transformers (`cross-encoder/ms-marco-MiniLM-L-6-v2`) |
| LLM (parsing + filters) | Groq SDK |
| Scraping | python-jobspy, Playwright, trafilatura, ddgs |
| Package manager | uv workspace |
