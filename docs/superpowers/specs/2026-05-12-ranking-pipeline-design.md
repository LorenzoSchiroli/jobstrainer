# Ranking Pipeline Design

**Date:** 2026-05-12
**Status:** Approved

## Overview

Add a hybrid retrieval + reranking pipeline to surface the most relevant job offers given a user's CV and a free-text query. Two services are extended:

1. **Ingestion service** — generates a bi-encoder embedding per job at write time and includes it in the backend POST.
2. **Backend** — stores embeddings + FTS vectors, exposes `POST /jobs/search` that runs query understanding → pre-filter → hybrid retrieval → cross-encoder reranking.

## Architecture

```
User (CV + query)
        │
        ▼
POST /jobs/search (backend)
        │
        ├─ 1. Query understanding (Groq) → SearchFilters + semantic_query
        ├─ 2. SQL pre-filter (WHERE on jobs + companies)
        ├─ 3. Hybrid retrieval: RRF(vector_ranked, fts_ranked) → top-50
        ├─ 4. Cross-encoder reranking → top-20
        └─ 5. Return ranked JobResponse list
```

At ingestion time:

```
Scrape → Enrich (Groq) → Embed (bge-small-en-v1.5) → POST /jobs (with embedding)
```

## Data Layer

### New columns on `jobs`

| Column | Type | Purpose |
|---|---|---|
| `embedding` | `vector(384)` | Bi-encoder output from `BAAI/bge-small-en-v1.5` |
| `search_vector` | `tsvector` | Weighted FTS index for keyword retrieval |

Both columns are nullable — existing jobs without embeddings are excluded from search until re-ingested.

### Indexes

- **HNSW** on `embedding` (pgvector) — approximate nearest-neighbor vector search
- **GIN** on `search_vector` — fast FTS matching

### search_vector computation

Computed by the backend on every job upsert (not a DB trigger):

```sql
setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
setweight(to_tsvector('english', coalesce(description, '')), 'B')
```

Title gets weight A (higher relevance), description gets weight B.

### Migration

A new Alembic migration (`002_embeddings.py`) that:
1. `CREATE EXTENSION IF NOT EXISTS vector`
2. `ALTER TABLE jobs ADD COLUMN embedding vector(384)`
3. `ALTER TABLE jobs ADD COLUMN search_vector tsvector`
4. Creates the HNSW and GIN indexes

## Embedding Generation (Ingestion)

### Model

`BAAI/bge-small-en-v1.5` — 512-token context window, 384-dimensional output. Covers the vast majority of job descriptions without truncation. Loaded once at pipeline startup, reused across all offers in a batch.

### Embedded text

```
{title}\n{description}
```

Sentence-transformers handles truncation at 512 tokens for any descriptions that exceed the limit.

### Module

New `ingestion/ingestion/embedder.py`:

```python
from sentence_transformers import SentenceTransformer

_model: SentenceTransformer | None = None

def get_embedder() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer("BAAI/bge-small-en-v1.5")
    return _model

def embed(title: str, description: str | None) -> list[float]:
    text = f"{title}\n{description or ''}"
    return get_embedder().encode(text).tolist()
```

### Pipeline integration

Embedding is generated after Groq enrichment, before the backend POST:

```
enrich_all() → embed(offer.title, offer.description) → post_job(offer, embedding=vec)
```

`JobRequest` gets one new optional field: `embedding: list[float] | None = None`. The backend stores it as-is; no validation of dimensionality at the API layer.

### Dependency

`sentence-transformers` added to `ingestion/pyproject.toml`. The ingestion Dockerfile pre-downloads the model at build time to avoid cold-start delays.

## Ranking API (Backend)

### Endpoint

```
POST /jobs/search
```

**Request:**
```json
{
  "cv_text": "...",
  "query": "senior ML engineer, product company, remote"
}
```

**Response:** array of a new `JobSearchResponse` schema — extends `JobResponse` with a nested `company` object (name, is_consulting, is_startup, review_score, financial_health_score, industry, country). Ordered by relevance, max 20 results.

### SearchFilters

Defined in `backend/backend/search/filters.py`, co-located with the models it mirrors. Update this file when `Job` or `Company` columns change.

```python
class SearchFilters(BaseModel):
    # from companies
    is_consulting: bool | None = None
    is_startup: bool | None = None
    industry: str | None = None
    country: str | None = None
    employee_count: str | None = None
    min_review_score: float | None = None
    min_financial_health_score: int | None = None

    # from jobs
    employment_type: str | None = None
    location_type: str | None = None
    seniority: str | None = None
    languages_required: list[str] | None = None

    # always present — drives retrieval
    semantic_query: str
```

### Stage 1 — Query Understanding

Single Groq call with a system prompt that instructs the LLM to extract structured filters and a semantic query from the CV + user query. Response is parsed into `SearchFilters` via structured output / JSON mode.

The `semantic_query` combines CV context with the user's stated intent, e.g.: *"senior machine learning engineer Python MLOps Kubernetes product company remote EU timezone"*.

### Stage 2 — SQL Pre-filter

Dynamic `WHERE` clause built from non-null `SearchFilters` fields. Joins `jobs` and `companies`. Only jobs with `embedding IS NOT NULL` are considered.

Range filters (`min_review_score`, `min_financial_health_score`) use `>=`. Array filter (`languages_required`) uses `@>` (array contains).

### Stage 3 — Hybrid Retrieval (RRF)

Single SQL query with three CTEs:

```sql
WITH vector_ranked AS (
    SELECT j.id,
           ROW_NUMBER() OVER (ORDER BY j.embedding <=> :query_embedding) AS rank
    FROM jobs j JOIN companies c ON j.company_id = c.id
    WHERE j.embedding IS NOT NULL
      AND <dynamic filters>
    LIMIT 100
),
fts_ranked AS (
    SELECT j.id,
           ROW_NUMBER() OVER (
               ORDER BY ts_rank_cd(j.search_vector, plainto_tsquery('english', :query_text)) DESC
           ) AS rank
    FROM jobs j JOIN companies c ON j.company_id = c.id
    WHERE j.search_vector @@ plainto_tsquery('english', :query_text)
      AND <dynamic filters>
    LIMIT 100
),
rrf AS (
    SELECT COALESCE(v.id, f.id) AS id,
           COALESCE(1.0 / (60 + v.rank), 0) + COALESCE(1.0 / (60 + f.rank), 0) AS score
    FROM vector_ranked v
    FULL OUTER JOIN fts_ranked f ON v.id = f.id
)
SELECT j.*, rrf.score
FROM rrf JOIN jobs j ON rrf.id = j.id
ORDER BY rrf.score DESC
LIMIT 50
```

RRF constant k=60 (standard default). Returns top-50 candidates for reranking.

### Stage 4 — Cross-encoder Reranking

`cross-encoder/ms-marco-MiniLM-L-6-v2` scores each `(semantic_query, job.description)` pair. Returns top-20 by score.

```python
pairs = [(semantic_query, job.description or "") for job in candidates]
scores = reranker.predict(pairs)
ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
return [job for job, _ in ranked[:20]]
```

### Model Lifecycle

Both models (`bge-small-en-v1.5` for query encoding, `ms-marco` cross-encoder) are loaded in the FastAPI `lifespan` context and injected via `Depends`. Pre-downloaded in the backend Dockerfile. `GROQ_API_KEY` is added to the backend environment in docker-compose.

## New Files

| File | Service | Purpose |
|---|---|---|
| `ingestion/ingestion/embedder.py` | ingestion | Loads bge model, exposes `embed()` |
| `backend/backend/search/__init__.py` | backend | Package |
| `backend/backend/search/filters.py` | backend | `SearchFilters` Pydantic model |
| `backend/backend/search/query_understanding.py` | backend | Groq call → `SearchFilters` |
| `backend/backend/search/retrieval.py` | backend | Hybrid RRF SQL query |
| `backend/backend/search/reranker.py` | backend | Cross-encoder reranking |
| `backend/backend/routers/search.py` | backend | `POST /jobs/search` endpoint |
| `backend/alembic/versions/002_embeddings.py` | backend | pgvector extension + new columns + indexes |

## Modified Files

| File | Change |
|---|---|
| `ingestion/ingestion/pipeline/__main__.py` | Call `embed()`, include in `post_job()` |
| `ingestion/ingestion/client.py` | Accept `embedding` param in `post_job()` |
| `ingestion/pyproject.toml` | Add `sentence-transformers` |
| `ingestion/Dockerfile` | Pre-download bge model at build time |
| `backend/backend/schemas.py` | Add `embedding: list[float] | None` to `JobRequest`; add `JobSearchResponse` |
| `backend/backend/routers/jobs.py` | Compute + store `search_vector` on upsert |
| `backend/backend/models.py` | Add `embedding` + `search_vector` columns |
| `backend/backend/main.py` | Load models in `lifespan`, register search router |
| `backend/pyproject.toml` | Add `sentence-transformers`, `groq`, `pgvector` |
| `backend/Dockerfile` | Pre-download cross-encoder model at build time |
| `docker-compose.yml` | Add `GROQ_API_KEY` to backend environment |

## Out of Scope

- Re-embedding existing jobs (operator concern, not part of this feature)
- Streaming responses
- User authentication / per-user CV storage
- Feedback loop / relevance signals
