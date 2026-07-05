# Design: Postgres as source of truth for job embeddings

## Problem

Job embeddings (384-dim vectors from `BAAI/bge-small-en-v1.5`, computed by ingestion) are currently only stored in OpenSearch. `routers/jobs.py` strips `embedding` out of the row data before saving the `Job` to Postgres, and stashes it instead in the `Outbox.payload` JSON so `outbox/worker.py` can push it straight into OpenSearch. If the OpenSearch index is ever rebuilt, the embeddings are gone — Postgres has no copy.

This breaks the project's outbox pattern, where Postgres is meant to be the single source of truth and OpenSearch a replica populated from it. Every other job field follows that pattern; `embedding` does not.

## Goals

- Store the embedding on the `Job` row in Postgres.
- Outbox worker reads the embedding off the Postgres row (like every other field) instead of carrying it through the event payload.
- Postgres never queries/indexes on the embedding — it's a payload column only, replicated onward to OpenSearch for k-NN search.
- One-time backfill of embeddings for existing jobs (current embeddings were lost).

## Non-goals

- No pgvector extension, no vector operations in Postgres.
- No change to OpenSearch mapping, hybrid retrieval, or the embedding model.
- No change to update semantics for other fields.

## Design

### Schema

Add a nullable column to `Job` in `backend/backend/models.py`:

```python
embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float))
```

New Alembic migration `backend/alembic/versions/010_add_job_embedding.py` adding this column.

### Write path (`backend/backend/routers/jobs.py`)

- Remove the special-casing of `embedding`: stop excluding it from `job_data = body.model_dump(exclude={"company_name", "embedding"})` — just exclude `company_name`.
- The existing fill-only merge logic already handles it correctly once it's a normal field:
  - New job: `Job(company_id=company.id, **job_data)` sets `embedding` like any other field.
  - Existing job: `if field != "url" and not _is_empty(value) and _is_empty(getattr(job, field))` — embedding is set once and not overwritten on subsequent upserts, consistent with every other field (e.g. `summary`, `description`).
- `Outbox` insert no longer carries the embedding: `payload={}` instead of `payload={"embedding": embedding}`. `Outbox.payload` is `NOT NULL` JSONB, so `{}` is valid.

### Outbox worker (`backend/backend/outbox/worker.py`)

- `_build_job_doc(job, embedding)` → `_build_job_doc(job)`, reading `job.embedding` directly instead of taking it as a parameter.
- `_handle_job_upserted` drops `event.payload.get("embedding")` and just calls `_build_job_doc(job)`.

### `JobRequest` schema (`backend/backend/schemas.py`)

No change — `embedding: list[float] | None = None` already exists and ingestion already sends it via `ingestion/ingestion/client.py:post_job`.

### Backfill (one-time, throwaway)

A standalone script, e.g. `backend/scripts/backfill_embeddings.py`, run once to recompute embeddings for existing jobs and delete afterward — this is not a permanent part of the codebase.

1. Query `Job` rows where `embedding IS NULL`.
2. For each, reuse `get_biencoder()` (`backend/backend/search/models_lifecycle.py`, already loads `BAAI/bge-small-en-v1.5` — the same model ingestion uses) and the same summary-flattening logic currently in `outbox/worker.py::_flatten_summary` to build `f"{title}\n{summary_text}"`.
3. Skip jobs with no summary (nothing to embed, matches `ingestion/ingestion/embedder.py::embed`'s behavior of returning `None`).
4. Set `job.embedding` on the row and insert an empty-payload `job_upserted` Outbox event for that job ID, so the existing outbox worker loop replicates the recomputed embedding into OpenSearch — no separate OpenSearch-writing code needed in the script.
5. Commit in batches.

Delete the script once the backfill has run successfully against production data.

## Testing

- Update `backend/tests/` coverage for `routers/jobs.py` (embedding persisted on create, not overwritten on update-with-existing-embedding) and `outbox/worker.py` (`_build_job_doc` reads from the row).
- No new tests for the backfill script since it's throwaway; a manual dry run against a small batch is sufficient before running it for real.
