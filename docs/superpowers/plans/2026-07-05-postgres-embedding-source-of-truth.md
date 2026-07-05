# Postgres Embedding Source of Truth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store job embeddings in Postgres (the source of truth) and have the outbox worker replicate them into OpenSearch, instead of the embedding only ever living in OpenSearch.

**Architecture:** Add a nullable `embedding` column to the `Job` table. `routers/jobs.py` stops special-casing `embedding` out of the row data — it flows through the same fill-only merge logic as every other field. The outbox worker reads `job.embedding` off the row it already loads, instead of pulling it from the `Outbox.payload` JSON. A throwaway script backfills embeddings for jobs that predate this change, then gets deleted.

**Tech Stack:** FastAPI, SQLAlchemy async (Postgres), Alembic, pytest + pytest-asyncio, sentence-transformers (`BAAI/bge-small-en-v1.5`).

## Global Constraints

- Postgres never queries or indexes on `embedding` — it is a payload column only, mirrored to OpenSearch for k-NN search (per spec `docs/superpowers/specs/2026-07-05-postgres-embedding-source-of-truth-design.md`).
- No pgvector extension.
- Embedding follows the existing fill-only update semantics used for every other `Job` field: set once, never overwritten by a later upsert.
- Backfill script is throwaway — delete it after it's been run successfully once.
- Tests run against a live Postgres at `TEST_DATABASE_URL` (defaults to `postgresql+asyncpg://postgres:postgres@localhost:5432/jobstrainer_test`); tables are created from `Base.metadata` directly in `backend/tests/conftest.py`, so no Alembic migration needs to run for tests to pick up the new column.

---

### Task 1: Add `embedding` column to the `Job` model + Alembic migration

**Files:**
- Modify: `backend/backend/models.py:1-4` (imports), `backend/backend/models.py:49-71` (`Job` class)
- Create: `backend/alembic/versions/010_add_job_embedding.py`
- Test: `backend/tests/test_job_embedding_column.py`

**Interfaces:**
- Produces: `Job.embedding: list[float] | None` — a plain ORM attribute, settable and readable like any other column. Tasks 2 and 3 read/write it directly.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_job_embedding_column.py`:

```python
from backend.models import Company, Job


async def test_job_row_persists_embedding(db_session):
    company = Company(name="acme")
    db_session.add(company)
    await db_session.flush()

    job = Job(url="https://example.com/embed-1", title="Engineer", company_id=company.id, embedding=[0.1, 0.2, 0.3])
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    assert job.embedding == [0.1, 0.2, 0.3]


async def test_job_row_embedding_defaults_to_none(db_session):
    company = Company(name="acme2")
    db_session.add(company)
    await db_session.flush()

    job = Job(url="https://example.com/embed-2", title="Engineer", company_id=company.id)
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    assert job.embedding is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_job_embedding_column.py -v`
Expected: FAIL with `TypeError: 'embedding' is an invalid keyword argument for Job` (column doesn't exist yet)

- [ ] **Step 3: Add the column to the model**

In `backend/backend/models.py`, update the import line (currently line 3):

```python
from sqlalchemy import Boolean, Float, Integer, Text, ForeignKey, DateTime
```

to:

```python
from sqlalchemy import Boolean, Float, Integer, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import ARRAY
```

(Keep the existing `from sqlalchemy.dialects.postgresql import UUID, JSONB` line as-is; add the `ARRAY` import as its own line right after it.)

Then add the column to the `Job` class, right after `summary` (currently `backend/backend/models.py:67`):

```python
    summary: Mapped[dict | None] = mapped_column(JSONB)
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_job_embedding_column.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Add the Alembic migration**

Create `backend/alembic/versions/010_add_job_embedding.py`:

```python
"""add embedding to jobs

Revision ID: 010
Revises: 009
Create Date: 2026-07-05
"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("embedding", postgresql.ARRAY(sa.Float()), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "embedding")
```

- [ ] **Step 6: Commit**

```bash
cd backend && git add backend/models.py alembic/versions/010_add_job_embedding.py tests/test_job_embedding_column.py
git commit -m "feat: add embedding column to Job model"
```

---

### Task 2: Persist embedding through `routers/jobs.py`, simplify outbox payload

**Files:**
- Modify: `backend/backend/routers/jobs.py:33-52`
- Test: `backend/tests/test_jobs.py`

**Interfaces:**
- Consumes: `Job.embedding` (Task 1).
- Produces: `Job.embedding` is now set on create/upsert via the same fill-only path as `seniority`, `location`, etc. `Outbox` rows for `job_upserted` now always have `payload={}` — Task 3 relies on this (it stops reading `payload["embedding"]`).

- [ ] **Step 1: Update existing test to match the new payload shape, and add a fill-only test for embedding**

In `backend/tests/test_jobs.py`, replace the existing `test_job_upsert_creates_outbox_event` test:

```python
from sqlalchemy import select
from backend.models import Outbox


async def test_job_upsert_creates_outbox_event(client, db_session):
    await client.post("/jobs/", json={
        "url": "https://example.com/outbox-test",
        "title": "Engineer",
        "company_name": "Acme",
        "embedding": [0.5] * 384,
    })
    result = await db_session.execute(
        select(Outbox).where(Outbox.event_type == "job_upserted")
    )
    events = result.scalars().all()
    assert len(events) == 1
    assert events[0].payload == {}
```

with:

```python
from sqlalchemy import select
from backend.models import Outbox, Job


async def test_job_upsert_creates_outbox_event(client, db_session):
    await client.post("/jobs/", json={
        "url": "https://example.com/outbox-test",
        "title": "Engineer",
        "company_name": "Acme",
        "embedding": [0.5] * 384,
    })
    result = await db_session.execute(
        select(Outbox).where(Outbox.event_type == "job_upserted")
    )
    events = result.scalars().all()
    assert len(events) == 1
    assert events[0].payload == {}


async def test_create_job_persists_embedding_in_postgres(client, db_session):
    resp = await client.post("/jobs/", json={
        "url": "https://example.com/embed-persist",
        "title": "Engineer",
        "company_name": "Acme",
        "embedding": [0.25] * 384,
    })
    job_id = resp.json()["id"]
    result = await db_session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one()
    assert job.embedding == [0.25] * 384


async def test_upsert_job_does_not_overwrite_existing_embedding(client, db_session):
    await client.post("/jobs/", json={
        "url": "https://example.com/embed-fill-only",
        "title": "Engineer",
        "company_name": "Acme",
        "embedding": [0.1] * 384,
    })
    resp = await client.post("/jobs/", json={
        "url": "https://example.com/embed-fill-only",
        "title": "Engineer",
        "company_name": "Acme",
        "embedding": [0.9] * 384,
    })
    job_id = resp.json()["id"]
    result = await db_session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one()
    assert job.embedding == [0.1] * 384
```

- [ ] **Step 2: Run tests to verify the new/changed ones fail**

Run: `cd backend && uv run pytest tests/test_jobs.py -v`
Expected: `test_job_upsert_creates_outbox_event` FAILS (payload still contains `{"embedding": [...]}`); `test_create_job_persists_embedding_in_postgres` FAILS (`job.embedding` is `None`); `test_upsert_job_does_not_overwrite_existing_embedding` FAILS

- [ ] **Step 3: Update the router**

In `backend/backend/routers/jobs.py`, replace lines 33-34:

```python
    embedding = body.embedding
    job_data = body.model_dump(exclude={"company_name", "embedding"})
```

with:

```python
    job_data = body.model_dump(exclude={"company_name"})
```

Replace lines 48-52:

```python
    session.add(Outbox(
        event_type="job_upserted",
        entity_id=job.id,
        payload={"embedding": embedding},
    ))
```

with:

```python
    session.add(Outbox(
        event_type="job_upserted",
        entity_id=job.id,
        payload={},
    ))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_jobs.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
cd backend && git add backend/routers/jobs.py tests/test_jobs.py
git commit -m "feat: persist job embedding to Postgres instead of outbox payload"
```

---

### Task 3: Outbox worker reads embedding from the Postgres row

**Files:**
- Modify: `backend/backend/outbox/worker.py:26-55`
- Test: `backend/tests/test_outbox_worker.py`

**Interfaces:**
- Consumes: `Job.embedding` (Task 1).
- Produces: `_build_job_doc(job: Job) -> dict` (signature changed — no longer takes `embedding` as a second argument).

- [ ] **Step 1: Update the existing test to set embedding on the Job row directly**

In `backend/tests/test_outbox_worker.py`, replace `test_job_event_indexes_in_opensearch`:

```python
async def test_job_event_indexes_in_opensearch(db_session):
    company = await _company(db_session)
    job = await _job(db_session, company.id)
    db_session.add(Outbox(event_type="job_upserted", entity_id=job.id, payload={"embedding": [0.1] * 384}))
    await db_session.commit()

    mock_os = AsyncMock()
    await process_pending_events(db_session, mock_os)

    mock_os.index.assert_called_once()
    kwargs = mock_os.index.call_args.kwargs
    assert kwargs["id"] == str(job.id)
    assert kwargs["body"]["embedding"] == [0.1] * 384

    result = await db_session.execute(select(Outbox))
    event = result.scalar_one()
    assert event.processed_at is not None
```

with:

```python
async def test_job_event_indexes_in_opensearch(db_session):
    company = await _company(db_session)
    job = await _job(db_session, company.id)
    job.embedding = [0.1] * 384
    db_session.add(Outbox(event_type="job_upserted", entity_id=job.id, payload={}))
    await db_session.commit()

    mock_os = AsyncMock()
    await process_pending_events(db_session, mock_os)

    mock_os.index.assert_called_once()
    kwargs = mock_os.index.call_args.kwargs
    assert kwargs["id"] == str(job.id)
    assert kwargs["body"]["embedding"] == [0.1] * 384

    result = await db_session.execute(select(Outbox))
    event = result.scalar_one()
    assert event.processed_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_outbox_worker.py::test_job_event_indexes_in_opensearch -v`
Expected: FAIL on `assert kwargs["body"]["embedding"] == [0.1] * 384` (got `None`) — the worker still reads `event.payload.get("embedding")`, and payload is now `{}`, so it builds the doc with `embedding: None` even though `job.embedding` is set on the row.

- [ ] **Step 3: Update the worker**

In `backend/backend/outbox/worker.py`, replace lines 26-44:

```python
def _build_job_doc(job: Job, embedding: list[float] | None) -> dict:
    c = job.company
    return {
        "job_id": str(job.id),
        "company_id": str(job.company_id),
        "title": job.title,
        "description": job.description or "",
        "summary_text": _flatten_summary(job.summary),
        "embedding": embedding,
        "employment_type": job.employment_type,
        "location_type": job.location_type,
        "seniority": job.seniority,
        "languages_required": job.languages_required or [],
        "is_consulting": c.is_consulting if c else None,
        "is_startup": c.is_startup if c else None,
        "industry": c.industry if c else None,
        "country": c.country if c else None,
        "review_score": c.review_score if c else None,
        "financial_health_score": c.financial_health_score if c else None,
        "created_at": job.created_at.isoformat(),
    }
```

with:

```python
def _build_job_doc(job: Job) -> dict:
    c = job.company
    return {
        "job_id": str(job.id),
        "company_id": str(job.company_id),
        "title": job.title,
        "description": job.description or "",
        "summary_text": _flatten_summary(job.summary),
        "embedding": job.embedding,
        "employment_type": job.employment_type,
        "location_type": job.location_type,
        "seniority": job.seniority,
        "languages_required": job.languages_required or [],
        "is_consulting": c.is_consulting if c else None,
        "is_startup": c.is_startup if c else None,
        "industry": c.industry if c else None,
        "country": c.country if c else None,
        "review_score": c.review_score if c else None,
        "financial_health_score": c.financial_health_score if c else None,
        "created_at": job.created_at.isoformat(),
    }
```

Then replace lines 47-55:

```python
async def _handle_job_upserted(event: Outbox, session: AsyncSession, os_client: AsyncOpenSearch) -> None:
    result = await session.execute(
        select(Job).options(selectinload(Job.company)).where(Job.id == event.entity_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        return
    doc = _build_job_doc(job, event.payload.get("embedding"))
    await os_client.index(index=INDEX_NAME, id=str(job.id), body=doc)
```

with:

```python
async def _handle_job_upserted(event: Outbox, session: AsyncSession, os_client: AsyncOpenSearch) -> None:
    result = await session.execute(
        select(Job).options(selectinload(Job.company)).where(Job.id == event.entity_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        return
    doc = _build_job_doc(job)
    await os_client.index(index=INDEX_NAME, id=str(job.id), body=doc)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_outbox_worker.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Run the full backend suite to check nothing else broke**

Run: `cd backend && uv run pytest -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
cd backend && git add backend/outbox/worker.py tests/test_outbox_worker.py
git commit -m "feat: outbox worker reads job embedding from Postgres row"
```

---

### Task 4: One-time backfill script (throwaway)

**Files:**
- Create: `backend/scripts/backfill_embeddings.py`

**Interfaces:**
- Consumes: `Job.embedding` (Task 1), `Job.summary` (existing), `backend.database.get_session_factory` (existing), `backend.search.models_lifecycle.init_models` / `get_biencoder` (existing).
- Produces: nothing consumed by other tasks — this script is deleted after use.

This task has no automated test (per the spec: the script is throwaway, a manual dry run is sufficient). Steps are manual verification instead of pytest cycles.

- [ ] **Step 1: Write the script**

Create `backend/scripts/backfill_embeddings.py`:

```python
"""One-time backfill: recompute embeddings for jobs whose Postgres `embedding`
column is empty (they predate storing embeddings in Postgres).

Run from the backend/ directory:
    uv run python scripts/backfill_embeddings.py

Delete this script once it has been run successfully against production data.
"""
import asyncio

from sqlalchemy import select

from backend.database import get_session_factory
from backend.models import Job, Outbox
from backend.search.models_lifecycle import init_models, get_biencoder


def _flatten_summary(summary: dict | None) -> str:
    if not summary:
        return ""
    parts = (
        summary.get("role_info", []) +
        summary.get("requirements", []) +
        summary.get("responsibilities", []) +
        summary.get("domain", [])
    )
    return " ".join(parts)


async def backfill(batch_size: int = 100) -> None:
    init_models()
    model = get_biencoder()
    factory = get_session_factory()

    async with factory() as session:
        result = await session.execute(select(Job).where(Job.embedding.is_(None)))
        jobs = result.scalars().all()
        print(f"Found {len(jobs)} jobs missing embeddings")

        updated = 0
        skipped = 0
        for job in jobs:
            text = _flatten_summary(job.summary)
            if not text.strip():
                skipped += 1
                continue
            job.embedding = model.encode(f"{job.title}\n{text}").tolist()
            session.add(Outbox(event_type="job_upserted", entity_id=job.id, payload={}))
            updated += 1
            if updated % batch_size == 0:
                await session.commit()
                print(f"Committed {updated} so far...")

        await session.commit()
        print(f"Done. Updated {updated} jobs, skipped {skipped} with no summary text.")


if __name__ == "__main__":
    asyncio.run(backfill())
```

- [ ] **Step 2: Dry-run verification against the test database**

Run against the test DB to confirm it behaves correctly before touching production data:

```bash
cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/jobstrainer_test \
  DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/jobstrainer_test \
  uv run python -c "
import asyncio
from backend.database import get_session_factory
from backend.models import Company, Job

async def seed():
    factory = get_session_factory()
    async with factory() as session:
        c = Company(name='dryrun-co')
        session.add(c)
        await session.flush()
        session.add(Job(
            url='https://example.com/dryrun-1',
            title='ML Engineer',
            company_id=c.id,
            summary={'role_info': ['builds models'], 'requirements': ['Python'], 'responsibilities': [], 'domain': []},
        ))
        await session.commit()

asyncio.run(seed())
"
uv run python scripts/backfill_embeddings.py
```

Expected output: `Found 1 jobs missing embeddings` ... `Done. Updated 1 jobs, skipped 0 with no summary text.`

Verify the row was updated:

```bash
uv run python -c "
import asyncio
from sqlalchemy import select
from backend.database import get_session_factory
from backend.models import Job

async def check():
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(Job).where(Job.url == 'https://example.com/dryrun-1'))
        job = result.scalar_one()
        print('embedding length:', len(job.embedding) if job.embedding else None)

asyncio.run(check())
"
```

Expected: `embedding length: 384`

- [ ] **Step 3: Commit the script**

```bash
cd backend && git add scripts/backfill_embeddings.py
git commit -m "chore: add one-time embedding backfill script"
```

- [ ] **Step 4: Run against production, then delete the script**

This step is manual and run by the user against the real database (not part of automated execution):

```bash
cd backend && uv run python scripts/backfill_embeddings.py
```

After confirming it completed successfully and the outbox worker has drained the resulting `job_upserted` events into OpenSearch:

```bash
cd backend && git rm scripts/backfill_embeddings.py
git commit -m "chore: remove one-time embedding backfill script"
```
