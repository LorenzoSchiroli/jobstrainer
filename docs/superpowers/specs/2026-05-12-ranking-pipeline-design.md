# Ranking Pipeline Design

**Date:** 2026-05-12
**Last updated:** 2026-05-17
**Status:** Approved

## Overview

Add a hybrid retrieval + reranking pipeline to surface the most relevant job offers given a user's CV and a free-text query. The system uses two stores:

- **PostgreSQL** — source of truth for jobs and companies. All writes go here first.
- **OpenSearch** — search index. Stores a denormalized, searchable representation of each job. Never written to directly by clients — only the outbox worker writes here.

Three services are involved:

1. **Ingestion** — generates a bi-encoder embedding from `summary` at write time and includes it in the backend POST.
2. **Backend** — upserts into Postgres + outbox atomically; background worker drains outbox into OpenSearch; exposes `POST /jobs/search`.
3. **OpenSearch** — handles BM25 on `description`, k-NN on `embedding`, structured filtering, and score normalization.

## Architecture

```
Ingestion pipeline:
  Scrape → Enrich (Groq) → Embed (bge-small-en-v1.5 on summary) → POST /jobs

Backend write path:
  POST /jobs  → upsert jobs table      ┐ single transaction
              → insert outbox event    ┘
  POST /companies → upsert companies   ┐ single transaction
                 → insert outbox event ┘

Outbox worker (background, inside backend container):
  poll outbox → for job event:     read job+company from Postgres → index doc in OpenSearch
             → for company event:  read company from Postgres → update_by_query in OpenSearch

Search path:
  POST /jobs/search
    ├─ 1. Query understanding (Groq) → SearchFilters + semantic_query
    ├─ 2. Encode semantic_query → embedding (biencoder, in backend)
    ├─ 3. OpenSearch hybrid query (BM25 + k-NN + filter) → top-50
    ├─ 4. Cross-encoder reranking on summary_text → top-20
    └─ 5. Return ranked JobSearchResponse list
```

## Infrastructure

```yaml
# docker-compose.yml additions
postgres:
  image: postgres:16          # unchanged — no special extensions needed

opensearch:
  image: opensearchproject/opensearch:2
  environment:
    - discovery.type=single_node
    - DISABLE_SECURITY_PLUGIN=true
  ports:
    - "9200:9200"

backend:
  environment:
    OPENSEARCH_URL: http://opensearch:9200
    GROQ_API_KEY: ${GROQ_API_KEY}   # new
  depends_on:
    opensearch:
      condition: service_healthy
```

OpenSearch healthcheck: `curl -s http://localhost:9200/_cluster/health`.

## Data Layer

### PostgreSQL

No new columns on `jobs` or `companies`. One new table:

```sql
CREATE TABLE outbox (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type  TEXT NOT NULL,   -- 'job_upserted' | 'company_upserted'
    entity_id   UUID NOT NULL,
    payload     JSONB NOT NULL,  -- includes embedding array for job events
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ
);
CREATE INDEX outbox_unprocessed_idx ON outbox (created_at)
    WHERE processed_at IS NULL;
```

The `payload` for a `job_upserted` event includes the embedding array (384 floats, ~3 KB as JSON). This avoids adding a vector column to `jobs` while still making the embedding available to the worker.

**No pgvector extension required.** Standard Postgres 16.

Migration: `backend/alembic/versions/005_outbox.py`.

### OpenSearch index

Index name: `jobs`. Created by the backend at startup if it does not exist.

**Mapping:**

```json
{
  "settings": {
    "index": { "knn": true }
  },
  "mappings": {
    "properties": {
      "job_id":               { "type": "keyword" },
      "company_id":           { "type": "keyword" },
      "title":                { "type": "text" },
      "description":          { "type": "text" },
      "summary_text":         { "type": "text" },
      "embedding": {
        "type": "knn_vector",
        "dimension": 384,
        "method": {
          "name": "hnsw",
          "space_type": "cosinesimil",
          "engine": "lucene"
        }
      },
      "employment_type":      { "type": "keyword" },
      "location_type":        { "type": "keyword" },
      "seniority":            { "type": "keyword" },
      "languages_required":   { "type": "keyword" },
      "is_consulting":        { "type": "boolean" },
      "is_startup":           { "type": "boolean" },
      "industry":             { "type": "keyword" },
      "country":              { "type": "keyword" },
      "review_score":         { "type": "float" },
      "financial_health_score": { "type": "integer" }
    }
  }
}
```

`summary_text` is the flattened `OfferSummary` (all four list fields joined as space-separated text). Used as the cross-encoder document input. `description` is the full job description — BM25 target, no token-length constraint.

**Search pipeline** (created at startup, used for hybrid score normalization):

```json
PUT /_search/pipeline/hybrid-pipeline
{
  "phase_results_processors": [{
    "normalization-processor": {
      "normalization": { "technique": "min_max" },
      "combination": {
        "technique": "arithmetic_mean",
        "parameters": { "weights": [0.5, 0.5] }
      }
    }
  }]
}
```

## Embedding Generation (Ingestion)

### Model

`BAAI/bge-small-en-v1.5` — 512-token context window, 384-dimensional output. Applied to `summary`, which is short by design and fits within the token budget.

### Embedded text

`OfferSummary` has four `list[str]` fields: `role_info`, `requirements`, `responsibilities`, `domain`. These are flattened before embedding:

```
{title}\n{role_info} {requirements} {responsibilities} {domain}
```

If `summary` is absent or all lists are empty, `embed()` returns `None`. The job is still indexed in OpenSearch (via BM25 on description) but the k-NN leg is skipped for that document.

### Module

New `ingestion/ingestion/embedder.py`:

```python
from sentence_transformers import SentenceTransformer
from ingestion.offer.models import OfferSummary

_model: SentenceTransformer | None = None

def get_embedder() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer("BAAI/bge-small-en-v1.5")
    return _model

def _summary_text(summary: OfferSummary) -> str:
    parts = summary.role_info + summary.requirements + summary.responsibilities + summary.domain
    return " ".join(parts)

def embed(title: str, summary: OfferSummary | None) -> list[float] | None:
    if not summary:
        return None
    text = _summary_text(summary)
    if not text.strip():
        return None
    return get_embedder().encode(f"{title}\n{text}").tolist()
```

### Pipeline integration

```
enrich_all() → embed(offer.title, offer.summary) → post_job(offer, embedding=vec)
```

`JobRequest` gets two new optional fields:
- `summary: dict | None = None` — the serialized `OfferSummary` (already in DB model since migration 004, but currently missing from schema and never stored)
- `embedding: list[float] | None = None` — forwarded to the outbox payload

### Dependency

`sentence-transformers` added to `ingestion/pyproject.toml`. Pre-downloaded in the ingestion Dockerfile.

## Outbox Worker (Backend)

Runs as an `asyncio.Task` started in the FastAPI `lifespan`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_models()
    task = asyncio.create_task(outbox_worker())
    yield
    task.cancel()
```

Worker loop (`backend/backend/outbox/worker.py`):

```python
async def outbox_worker():
    while True:
        await process_pending_events()
        await asyncio.sleep(1)
```

`process_pending_events` fetches up to 100 unprocessed outbox rows, dispatches each to the appropriate handler, and marks them processed:

- **`job_upserted`**: reads the full `Job` + `Company` from Postgres, builds the denormalized OpenSearch document (including embedding from payload), calls `opensearch.index()` using the job UUID as the document `_id` — makes indexing idempotent.
- **`company_upserted`**: reads the updated `Company` from Postgres, calls `opensearch.update_by_query()` to refresh all job documents with matching `company_id`.

If OpenSearch is unavailable, the event stays unprocessed and retried on the next poll cycle. The Postgres data is always safe.

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

**Response:** array of `JobSearchResponse` — extends `JobResponse` with a nested `company` object (name, is_consulting, is_startup, review_score, financial_health_score, industry, country). Ordered by relevance, max 20 results.

### SearchFilters

`backend/backend/search/filters.py`:

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

    # always present
    semantic_query: str
```

### Stage 1 — Query Understanding

Single Groq call → `SearchFilters` via JSON mode. `semantic_query` combines CV context with stated intent, e.g. *"senior machine learning engineer Python MLOps product company remote EU"*.

### Stage 2 — Query Embedding

`semantic_query` is encoded by `bge-small-en-v1.5` (same model as ingestion) into a 384-dim vector.

### Stage 3 — OpenSearch Hybrid Query

BM25 on `description` + k-NN on `embedding`, combined via the `hybrid-pipeline`. Structured filters applied to both legs via `bool.filter`.

```python
query = {
    "query": {
        "hybrid": {
            "queries": [
                {
                    "bool": {
                        "must": {"match": {"description": semantic_query}},
                        "filter": build_filters(filters),
                    }
                },
                {
                    "bool": {
                        "must": {
                            "knn": {
                                "embedding": {"vector": query_embedding, "k": 100}
                            }
                        },
                        "filter": build_filters(filters),
                    }
                },
            ]
        }
    },
    "size": 50,
}
response = opensearch.search(index="jobs", body=query,
                             params={"search_pipeline": "hybrid-pipeline"})
```

`build_filters(filters)` converts non-null `SearchFilters` fields to OpenSearch `term`/`range`/`terms` clauses. Returns top-50 hits.

### Stage 4 — Cross-encoder Reranking

`cross-encoder/ms-marco-MiniLM-L-6-v2` scores `(semantic_query, summary_text)` pairs. `summary_text` comes directly from the OpenSearch hit `_source` — no DB round-trip needed.

```python
pairs = [
    (semantic_query, hit["_source"].get("summary_text") or "")
    for hit in candidates
]
scores = reranker.predict(pairs)
ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
return [hit for hit, _ in ranked[:20]]
```

Jobs with no `summary_text` receive a low score but are not excluded.

The reranker returns a list of job UUIDs in ranked order (from `hit["_source"]["job_id"]`). The endpoint then fetches the full `Job` + `Company` records from Postgres in a single query (`WHERE jobs.id IN (...)`) and reconstructs the ranked order. This keeps the OpenSearch mapping lean while ensuring the response always reflects the freshest Postgres state.

### Model Lifecycle

Both models (`bge-small-en-v1.5`, `ms-marco` cross-encoder) loaded via `init_models()` in lifespan, exposed as `Depends`-injectable functions `get_biencoder()` / `get_reranker()`. Pre-downloaded in backend Dockerfile. OpenSearch client initialised in lifespan, index + search pipeline created if absent.

## New Files

| File | Service | Purpose |
|---|---|---|
| `ingestion/ingestion/embedder.py` | ingestion | `embed()` using bge model |
| `backend/backend/outbox/__init__.py` | backend | Package |
| `backend/backend/outbox/worker.py` | backend | Outbox poll loop + event handlers |
| `backend/backend/search/__init__.py` | backend | Package |
| `backend/backend/search/filters.py` | backend | `SearchFilters` Pydantic model + `build_filters()` |
| `backend/backend/search/query_understanding.py` | backend | Groq call → `SearchFilters` |
| `backend/backend/search/retrieval.py` | backend | OpenSearch hybrid query |
| `backend/backend/search/reranker.py` | backend | Cross-encoder reranking |
| `backend/backend/search/models_lifecycle.py` | backend | `init_models()`, `get_biencoder()`, `get_reranker()` |
| `backend/backend/routers/search.py` | backend | `POST /jobs/search` endpoint |
| `backend/alembic/versions/005_outbox.py` | backend | outbox table + index |

## Modified Files

| File | Change |
|---|---|
| `ingestion/ingestion/pipeline/__main__.py` | Call `embed()`, pass to `post_job()` |
| `ingestion/ingestion/client.py` | Accept `embedding` param in `post_job()` |
| `ingestion/pyproject.toml` | Add `sentence-transformers` |
| `ingestion/Dockerfile` | Pre-download bge model at build time |
| `backend/backend/schemas.py` | Add `summary: dict \| None` and `embedding: list[float] \| None` to `JobRequest`; add `JobSearchResponse` |
| `backend/backend/routers/jobs.py` | Exclude `embedding` from `Job` construction (no such column); write outbox event with embedding in payload, in same transaction |
| `backend/backend/routers/companies.py` | Write outbox event in same transaction as company upsert |
| `backend/backend/main.py` | `init_models()`, start outbox worker task, init OpenSearch client + index + pipeline, register search router |
| `backend/pyproject.toml` | Add `sentence-transformers`, `groq`, `opensearch-py[async]` |
| `backend/Dockerfile` | Pre-download cross-encoder model at build time |
| `docker-compose.yml` | Add OpenSearch service; add `OPENSEARCH_URL` + `GROQ_API_KEY` to backend environment |

## Out of Scope

- Re-embedding existing jobs (operator concern)
- Streaming responses
- User authentication / per-user CV storage
- Feedback loop / relevance signals
- SPLADE sparse retrieval (deferred)
- Exactly-once outbox delivery (at-least-once with idempotent OpenSearch index is sufficient)
