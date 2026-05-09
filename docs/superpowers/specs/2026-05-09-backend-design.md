# Backend Service Design

**Date:** 2026-05-09
**Status:** Approved

## Overview

A new `backend/` service that persists job listings and company profiles in PostgreSQL and exposes a REST API. The ingestion service will call this API to store enriched data. The backend is purely passive — it stores and retrieves, no scraping or enrichment logic.

## Architecture

The backend is a uv workspace member at `backend/` alongside `ingestion/`. It runs as a Docker container alongside a PostgreSQL container, orchestrated by a single `docker-compose.yml` at the repo root.

```
jobstrainer/
├── backend/
│   ├── pyproject.toml          # own deps: fastapi, sqlalchemy[asyncio], asyncpg, alembic, uvicorn
│   ├── alembic.ini
│   ├── alembic/
│   │   └── versions/
│   ├── backend/
│   │   ├── main.py             # FastAPI app, lifespan
│   │   ├── database.py         # async engine + session factory + get_session dependency
│   │   ├── models.py           # SQLAlchemy ORM models
│   │   ├── schemas.py          # Pydantic request/response schemas
│   │   └── routers/
│   │       ├── jobs.py
│   │       └── companies.py
│   └── Dockerfile
├── docker-compose.yml
└── pyproject.toml              # root workspace definition
```

**Stack:**
- Python 3.13, FastAPI, SQLAlchemy 2.x async, asyncpg, Alembic, uvicorn
- PostgreSQL 16

## Data Model

### `companies`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | server-generated |
| `name` | TEXT UNIQUE NOT NULL | normalized dedup key (lowercased + stripped) |
| `website` | TEXT | |
| `country` | TEXT | |
| `founded_year` | INT | |
| `employee_count` | TEXT | |
| `industry` | TEXT | |
| `is_consulting` | BOOL | |
| `is_startup` | BOOL | |
| `review_score` | FLOAT | |
| `review_count` | INT | |
| `description` | TEXT | |
| `financial_health_score` | INT | 1–5 |
| `financial_health_rationale` | TEXT | |
| `registration_numbers` | JSONB | |
| `created_at` | TIMESTAMPTZ | server default NOW() |
| `updated_at` | TIMESTAMPTZ | auto-updated on change |

### `jobs`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | server-generated |
| `url` | TEXT UNIQUE NOT NULL | dedup key |
| `company_id` | UUID FK → companies.id NOT NULL | |
| `title` | TEXT NOT NULL | |
| `location` | TEXT | |
| `source` | TEXT | |
| `posted_at` | TIMESTAMPTZ | |
| `description` | TEXT | |
| `employment_type` | TEXT | |
| `location_type` | TEXT | |
| `office` | TEXT | |
| `seniority` | TEXT | |
| `salary_range` | TEXT | |
| `languages_required` | JSONB | |
| `text_language` | TEXT | |
| `created_at` | TIMESTAMPTZ | server default NOW() |
| `updated_at` | TIMESTAMPTZ | auto-updated on change |

## Upsert / Deduplication Logic

**Key rule:** existing populated fields are never overwritten. Only `NULL` fields are filled on subsequent upserts.

**Companies:** dedup key is `name` normalized as `name.lower().strip()`. On upsert, fetch by normalized name; if found, update only columns that are currently `NULL` in the DB row.

**Jobs:** dedup key is `url`. On upsert, fetch by URL; if found, update only `NULL` columns.

**Auto-stub on job upsert:** when a job arrives with a `company_name` string, the backend normalizes it and upserts a minimal company record (name only) if one does not exist. The job is then linked via `company_id`. This allows jobs and companies to be ingested independently without ordering constraints.

## API Endpoints

### `POST /companies`
- **Body:** company fields (name required, all others optional)
- **Logic:** normalize name → upsert (fill-gaps)
- **Response:** full company record; `201` if created, `200` if updated/no-op

### `GET /companies/{company_id}`
- **Response:** full company record or `404`

### `POST /jobs`
- **Body:** job fields (`url`, `title`, `company_name` required). Note: the ingestion's `EnrichedOffer` model uses `company` for the same field — the ingestion must map `company` → `company_name` when calling this endpoint.
- **Logic:** auto-upsert company stub → upsert job (fill-gaps)
- **Response:** full job record; `201` if created, `200` if updated/no-op

### `GET /jobs/{job_id}`
- **Response:** full job record or `404`

## Error Handling

| Scenario | Response |
|---|---|
| Malformed request body | `422` (FastAPI/Pydantic automatic) |
| Record not found (GET) | `404 {"detail": "not found"}` |
| Unexpected server error | `500 {"detail": "internal server error"}` |

Errors are logged to stdout; stack traces are not included in API responses. DB connection failure on startup crashes the container immediately (Docker restarts it).

## Database Migrations

Alembic manages all schema changes as versioned migration scripts. `alembic upgrade head` is run as part of the container startup sequence before uvicorn starts. No `create_all()` in application code.

## Testing

- Framework: `pytest` + `pytest-asyncio`
- Location: `backend/tests/`
- DB: real PostgreSQL (no mocking) — uses the same Compose DB with a separate test database
- Files: `test_companies.py`, `test_jobs.py`
- Cases per router:
  - Insert new record → `201`, record present in DB
  - Upsert existing with new data → `200`, null fields filled, populated fields unchanged
  - Upsert existing with all fields already populated → `200`, no fields overwritten
  - GET existing record → `200` with full data
  - GET unknown ID → `404`
  - Job upsert auto-creates company stub if company doesn't exist
