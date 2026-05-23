# Ranking Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add hybrid BM25 + dense-vector retrieval with cross-encoder reranking using OpenSearch as the search layer, Postgres as source of truth, and an outbox pattern for sync.

**Architecture:** Postgres stores all structured data; an outbox table in the same DB ensures atomic dual-write. A background worker inside the backend container drains the outbox into OpenSearch. The search endpoint does query understanding → OpenSearch hybrid query (BM25 on description + k-NN on summary embedding) → cross-encoder reranking → Postgres round-trip for full response.

**Tech Stack:** FastAPI, SQLAlchemy async, OpenSearch 2.x (`opensearch-py[async]`), `sentence-transformers` (bge-small-en-v1.5 + ms-marco-MiniLM-L-6-v2 cross-encoder), Groq API, Alembic, uv workspace.

---

### Task 1: Add OpenSearch to docker-compose

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Replace the full docker-compose.yml**

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: jobstrainer
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5

  opensearch:
    image: opensearchproject/opensearch:2
    environment:
      - discovery.type=single_node
      - DISABLE_SECURITY_PLUGIN=true
    ports:
      - "9200:9200"
    healthcheck:
      test: ["CMD-SHELL", "curl -s http://localhost:9200/_cluster/health | grep -q 'green\\|yellow'"]
      interval: 10s
      timeout: 10s
      retries: 12
      start_period: 30s

  backend:
    build:
      context: .
      dockerfile: backend/Dockerfile
    environment:
      DATABASE_URL: postgresql+asyncpg://postgres:postgres@postgres:5432/jobstrainer
      OPENSEARCH_URL: http://opensearch:9200
      GROQ_API_KEY: ${GROQ_API_KEY}
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      opensearch:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\""]
      interval: 5s
      timeout: 5s
      retries: 12
      start_period: 30s

  ingestion:
    build:
      context: .
      dockerfile: ingestion/Dockerfile
    restart: unless-stopped
    environment:
      OFFER_QUERY: ${OFFER_QUERY}
      GROQ_API_KEY: ${GROQ_API_KEY}
      SERPERDEV_API_KEY: ${SERPERDEV_API_KEY}
      DDGS_PROXY: ${DDGS_PROXY:-}
      ADZUNA_APP_ID: ${ADZUNA_APP_ID:-}
      ADZUNA_APP_KEY: ${ADZUNA_APP_KEY:-}
      BACKEND_URL: http://backend:8000
    volumes:
      - ./data:/app/ingestion/data
    depends_on:
      backend:
        condition: service_healthy

volumes:
  postgres_data:
```

- [ ] **Step 2: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(infra): add OpenSearch service to docker-compose"
```

---

### Task 2: Add backend dependencies

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `uv.lock` (root)

- [ ] **Step 1: Update backend/pyproject.toml**

```toml
[project]
name = "backend"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.34.0",
    "sqlalchemy[asyncio]>=2.0.0",
    "asyncpg>=0.30.0",
    "alembic>=1.14.0",
    "pydantic>=2.13.0",
    "python-dotenv>=1.2.2",
    "groq>=1.2.0",
    "opensearch-py[async]>=2.7.0",
    "sentence-transformers>=3.0.0",
]

[dependency-groups]
dev = [
    "pytest>=9.0.3",
    "pytest-asyncio>=0.25.0",
    "httpx>=0.28.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 2: Update the lock file from repo root**

```bash
uv lock
```

Expected: `uv.lock` updated, no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/pyproject.toml uv.lock
git commit -m "feat(backend): add groq, opensearch-py[async], sentence-transformers"
```

---

### Task 3: Outbox migration and SQLAlchemy model

**Files:**
- Modify: `backend/backend/models.py`
- Create: `backend/alembic/versions/005_outbox.py`

- [ ] **Step 1: Add Outbox to models.py**

Full updated `backend/backend/models.py`:

```python
import uuid
from datetime import datetime
from sqlalchemy import Boolean, Float, Integer, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    website: Mapped[str | None] = mapped_column(Text)
    linkedin_url: Mapped[str | None] = mapped_column(Text)
    topic: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    founded_year: Mapped[int | None] = mapped_column(Integer)
    employee_count: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(Text)
    is_consulting: Mapped[bool | None] = mapped_column(Boolean)
    is_startup: Mapped[bool | None] = mapped_column(Boolean)
    review_score: Mapped[float | None] = mapped_column(Float)
    review_count: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    financial_health_score: Mapped[int | None] = mapped_column(Integer)
    financial_health_rationale: Mapped[str | None] = mapped_column(Text)
    registration_numbers: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    jobs: Mapped[list["Job"]] = relationship("Job", back_populates="company")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    description: Mapped[str | None] = mapped_column(Text)
    employment_type: Mapped[str | None] = mapped_column(Text)
    location_type: Mapped[str | None] = mapped_column(Text)
    office: Mapped[str | None] = mapped_column(Text)
    seniority: Mapped[str | None] = mapped_column(Text)
    salary_range: Mapped[str | None] = mapped_column(Text)
    languages_required: Mapped[list | None] = mapped_column(JSONB)
    text_language: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    company: Mapped["Company"] = relationship("Company", back_populates="jobs")


class Outbox(Base):
    __tablename__ = "outbox"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 2: Create backend/alembic/versions/005_outbox.py**

```python
"""add outbox table

Revision ID: 005
Revises: 004
Create Date: 2026-05-17
"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "outbox_unprocessed_idx",
        "outbox",
        ["created_at"],
        postgresql_where=sa.text("processed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("outbox_unprocessed_idx", table_name="outbox")
    op.drop_table("outbox")
```

- [ ] **Step 3: Write and run test**

Create `backend/tests/test_outbox_model.py`:

```python
import uuid
from backend.models import Outbox


async def test_outbox_row_can_be_inserted(db_session):
    event = Outbox(
        event_type="job_upserted",
        entity_id=uuid.uuid4(),
        payload={"embedding": [0.1, 0.2]},
    )
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)
    assert event.id is not None
    assert event.processed_at is None
```

```bash
cd backend && uv run pytest tests/test_outbox_model.py -v
```

Expected: PASS (conftest uses `Base.metadata.create_all` which now includes `Outbox`).

- [ ] **Step 4: Commit**

```bash
git add backend/backend/models.py backend/alembic/versions/005_outbox.py backend/tests/test_outbox_model.py
git commit -m "feat(backend): add outbox table for Postgres→OpenSearch sync"
```

---

### Task 4: Expose session factory from database.py

**Files:**
- Modify: `backend/backend/database.py`

The outbox worker needs sessions outside of request scope.

- [ ] **Step 1: Update database.py**

```python
import os
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_engine = None
_session_factory = None


def _init():
    global _engine, _session_factory
    if _engine is None:
        url = os.environ["DATABASE_URL"]
        _engine = create_async_engine(url, echo=False)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)


def get_session_factory() -> async_sessionmaker:
    _init()
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    _init()
    async with _session_factory() as session:
        yield session
```

- [ ] **Step 2: Run all existing tests**

```bash
cd backend && uv run pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/backend/database.py
git commit -m "feat(backend): expose get_session_factory for outbox worker"
```

---

### Task 5: Update backend schemas

**Files:**
- Modify: `backend/backend/schemas.py`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_jobs.py`:

```python
async def test_create_job_accepts_summary_and_embedding(client):
    resp = await client.post("/jobs/", json={
        "url": "https://example.com/job/schema-test",
        "title": "ML Engineer",
        "company_name": "Acme",
        "summary": {"role_info": ["builds models"], "requirements": ["Python"], "responsibilities": [], "domain": []},
        "embedding": [0.1] * 384,
    })
    assert resp.status_code == 201
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd backend && uv run pytest tests/test_jobs.py::test_create_job_accepts_summary_and_embedding -v
```

Expected: FAIL — extra fields rejected or ignored causing assertion failure.

- [ ] **Step 3: Replace schemas.py**

```python
import uuid
from datetime import datetime
from pydantic import BaseModel, field_validator


class CompanyRequest(BaseModel):
    name: str
    website: str | None = None
    country: str | None = None
    founded_year: int | None = None
    employee_count: str | None = None
    industry: str | None = None
    is_consulting: bool | None = None
    is_startup: bool | None = None
    review_score: float | None = None
    review_count: int | None = None
    description: str | None = None
    financial_health_score: int | None = None
    financial_health_rationale: str | None = None
    registration_numbers: dict[str, str] | None = None


class CompanyResponse(CompanyRequest):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobRequest(BaseModel):
    url: str
    title: str
    company_name: str
    location: str | None = None
    source: str | None = None
    posted_at: datetime | None = None
    description: str | None = None
    employment_type: str | None = None
    location_type: str | None = None
    office: str | None = None
    seniority: str | None = None
    salary_range: str | None = None
    languages_required: list[str] = []
    text_language: str | None = None
    summary: dict | None = None
    embedding: list[float] | None = None


class JobResponse(BaseModel):
    id: uuid.UUID
    url: str
    company_id: uuid.UUID
    title: str
    location: str | None = None
    source: str | None = None
    posted_at: datetime | None = None
    description: str | None = None
    employment_type: str | None = None
    location_type: str | None = None
    office: str | None = None
    seniority: str | None = None
    salary_range: str | None = None
    languages_required: list[str] = []
    text_language: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("languages_required", mode="before")
    @classmethod
    def coerce_null(cls, v: list[str] | None) -> list[str]:
        return v or []


class CompanyInSearch(BaseModel):
    name: str
    is_consulting: bool | None = None
    is_startup: bool | None = None
    review_score: float | None = None
    financial_health_score: int | None = None
    industry: str | None = None
    country: str | None = None

    model_config = {"from_attributes": True}


class JobSearchResponse(JobResponse):
    company: CompanyInSearch
```

- [ ] **Step 4: Run to verify test passes**

```bash
cd backend && uv run pytest tests/test_jobs.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/backend/schemas.py backend/tests/test_jobs.py
git commit -m "feat(backend): add summary+embedding to JobRequest, add JobSearchResponse"
```

---

### Task 6: Jobs router — outbox integration

**Files:**
- Modify: `backend/backend/routers/jobs.py`

`embedding` must be excluded from `Job(...)` (no such column) and stored in the outbox payload instead.

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_jobs.py`:

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
    assert events[0].payload["embedding"] == [0.5] * 384
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd backend && uv run pytest tests/test_jobs.py::test_job_upsert_creates_outbox_event -v
```

Expected: FAIL.

- [ ] **Step 3: Replace routers/jobs.py**

```python
import uuid
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models import Company, Job, Outbox
from backend.schemas import JobRequest, JobResponse
from backend.routers.companies import _normalize, _is_empty

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/", response_model=JobResponse, status_code=201)
async def upsert_job(body: JobRequest, response: Response, session: AsyncSession = Depends(get_session)):
    normalized_company = _normalize(body.company_name)
    company_result = await session.execute(select(Company).where(Company.name == normalized_company))
    company = company_result.scalar_one_or_none()
    if company is None:
        try:
            company = Company(name=normalized_company)
            session.add(company)
            await session.flush()
        except IntegrityError:
            await session.rollback()
            result = await session.execute(select(Company).where(Company.name == normalized_company))
            company = result.scalar_one()

    job_result = await session.execute(select(Job).where(Job.url == body.url))
    job = job_result.scalar_one_or_none()

    embedding = body.embedding
    job_data = body.model_dump(exclude={"company_name", "embedding"})

    if job is None:
        job = Job(company_id=company.id, **job_data)
        session.add(job)
        response.status_code = 201
    else:
        for field, value in job_data.items():
            if field != "url" and not _is_empty(value) and _is_empty(getattr(job, field)):
                setattr(job, field, value)
        response.status_code = 200

    await session.flush()

    session.add(Outbox(
        event_type="job_upserted",
        entity_id=job.id,
        payload={"embedding": embedding},
    ))

    await session.commit()
    await session.refresh(job)
    return job


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="not found")
    return job
```

- [ ] **Step 4: Run all tests**

```bash
cd backend && uv run pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/backend/routers/jobs.py backend/tests/test_jobs.py
git commit -m "feat(backend): write outbox event on job upsert"
```

---

### Task 7: Companies router — outbox integration

**Files:**
- Modify: `backend/backend/routers/companies.py`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_companies.py`:

```python
from sqlalchemy import select
from backend.models import Outbox


async def test_company_upsert_creates_outbox_event(client, db_session):
    await client.post("/companies/", json={"name": "TestCo", "industry": "tech"})
    result = await db_session.execute(
        select(Outbox).where(Outbox.event_type == "company_upserted")
    )
    events = result.scalars().all()
    assert len(events) == 1
    assert events[0].payload == {}
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd backend && uv run pytest tests/test_companies.py::test_company_upsert_creates_outbox_event -v
```

Expected: FAIL.

- [ ] **Step 3: Replace routers/companies.py**

```python
import uuid
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models import Company, Outbox
from backend.schemas import CompanyRequest, CompanyResponse

router = APIRouter(prefix="/companies", tags=["companies"])


def _normalize(name: str) -> str:
    return name.lower().strip()


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, list) and not value:
        return True
    return False


@router.post("/", response_model=CompanyResponse, status_code=201)
async def upsert_company(body: CompanyRequest, response: Response, session: AsyncSession = Depends(get_session)):
    normalized = _normalize(body.name)
    result = await session.execute(select(Company).where(Company.name == normalized))
    company = result.scalar_one_or_none()

    if company is None:
        data = body.model_dump()
        data["name"] = normalized
        company = Company(**data)
        session.add(company)
        response.status_code = 201
    else:
        data = body.model_dump(exclude={"name"})
        for field, value in data.items():
            if not _is_empty(value) and _is_empty(getattr(company, field)):
                setattr(company, field, value)
        response.status_code = 200

    await session.flush()

    session.add(Outbox(
        event_type="company_upserted",
        entity_id=company.id,
        payload={},
    ))

    await session.commit()
    await session.refresh(company)
    return company


@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company(company_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Company).where(Company.id == company_id))
    company = result.scalar_one_or_none()
    if company is None:
        raise HTTPException(status_code=404, detail="not found")
    return company
```

- [ ] **Step 4: Run all tests**

```bash
cd backend && uv run pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/backend/routers/companies.py backend/tests/test_companies.py
git commit -m "feat(backend): write outbox event on company upsert"
```

---

### Task 8: OpenSearch client module

**Files:**
- Create: `backend/backend/opensearch_client.py`
- Create: `backend/tests/test_opensearch_client.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_opensearch_client.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
import backend.opensearch_client as m


async def test_init_creates_index_when_missing(monkeypatch):
    monkeypatch.setenv("OPENSEARCH_URL", "http://localhost:9200")
    mock_client = AsyncMock()
    mock_client.indices.exists.return_value = False
    with patch("backend.opensearch_client.AsyncOpenSearch", return_value=mock_client):
        m._client = None
        await m.init_opensearch()
    mock_client.indices.create.assert_called_once()
    mock_client.transport.perform_request.assert_called_once()


async def test_init_skips_index_creation_when_exists(monkeypatch):
    monkeypatch.setenv("OPENSEARCH_URL", "http://localhost:9200")
    mock_client = AsyncMock()
    mock_client.indices.exists.return_value = True
    with patch("backend.opensearch_client.AsyncOpenSearch", return_value=mock_client):
        m._client = None
        await m.init_opensearch()
    mock_client.indices.create.assert_not_called()


def test_get_opensearch_raises_before_init():
    m._client = None
    with pytest.raises(AssertionError):
        m.get_opensearch()
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd backend && uv run pytest tests/test_opensearch_client.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 3: Create backend/backend/opensearch_client.py**

```python
import os
from opensearchpy import AsyncOpenSearch

_client: AsyncOpenSearch | None = None

INDEX_NAME = "jobs"
PIPELINE_NAME = "hybrid-pipeline"

_INDEX_BODY = {
    "settings": {"index": {"knn": True}},
    "mappings": {
        "properties": {
            "job_id":                   {"type": "keyword"},
            "company_id":               {"type": "keyword"},
            "title":                    {"type": "text"},
            "description":              {"type": "text"},
            "summary_text":             {"type": "text"},
            "embedding": {
                "type": "knn_vector",
                "dimension": 384,
                "method": {"name": "hnsw", "space_type": "cosine", "engine": "faiss"},
            },
            "employment_type":          {"type": "keyword"},
            "location_type":            {"type": "keyword"},
            "seniority":                {"type": "keyword"},
            "languages_required":       {"type": "keyword"},
            "is_consulting":            {"type": "boolean"},
            "is_startup":               {"type": "boolean"},
            "industry":                 {"type": "keyword"},
            "country":                  {"type": "keyword"},
            "review_score":             {"type": "float"},
            "financial_health_score":   {"type": "integer"},
        }
    },
}

_PIPELINE_BODY = {
    "description": "Hybrid BM25 + kNN normalization",
    "phase_results_processors": [{
        "normalization-processor": {
            "normalization": {"technique": "min_max"},
            "combination": {
                "technique": "arithmetic_mean",
                "parameters": {"weights": [0.5, 0.5]},
            },
        }
    }],
}


def get_opensearch() -> AsyncOpenSearch:
    assert _client is not None, "OpenSearch client not initialized"
    return _client


async def init_opensearch() -> None:
    global _client
    url = os.environ["OPENSEARCH_URL"]
    _client = AsyncOpenSearch(hosts=[url])
    if not await _client.indices.exists(index=INDEX_NAME):
        await _client.indices.create(index=INDEX_NAME, body=_INDEX_BODY)
    await _client.transport.perform_request(
        method="PUT",
        url=f"/_search/pipeline/{PIPELINE_NAME}",
        body=_PIPELINE_BODY,
    )
```

- [ ] **Step 4: Run to verify tests pass**

```bash
cd backend && uv run pytest tests/test_opensearch_client.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/backend/opensearch_client.py backend/tests/test_opensearch_client.py
git commit -m "feat(backend): add OpenSearch client with index and pipeline setup"
```

---

### Task 9: SearchFilters and build_filters

**Files:**
- Create: `backend/backend/search/__init__.py` (empty)
- Create: `backend/backend/search/filters.py`
- Create: `backend/tests/search/__init__.py` (empty)
- Create: `backend/tests/search/test_filters.py`

- [ ] **Step 1: Create the two empty `__init__.py` files**

```bash
touch backend/backend/search/__init__.py backend/tests/search/__init__.py
```

- [ ] **Step 2: Write failing tests**

Create `backend/tests/search/test_filters.py`:

```python
from backend.search.filters import SearchFilters, build_filters


def test_only_semantic_query_required():
    f = SearchFilters(semantic_query="python engineer")
    assert f.seniority is None


def test_build_filters_empty_when_all_none():
    assert build_filters(SearchFilters(semantic_query="x")) == []


def test_build_filters_term_bool():
    result = build_filters(SearchFilters(semantic_query="x", is_consulting=True))
    assert {"term": {"is_consulting": True}} in result


def test_build_filters_term_string():
    result = build_filters(SearchFilters(semantic_query="x", seniority="senior"))
    assert {"term": {"seniority": "senior"}} in result


def test_build_filters_range_review_score():
    result = build_filters(SearchFilters(semantic_query="x", min_review_score=4.0))
    assert {"range": {"review_score": {"gte": 4.0}}} in result


def test_build_filters_range_financial_health():
    result = build_filters(SearchFilters(semantic_query="x", min_financial_health_score=3))
    assert {"range": {"financial_health_score": {"gte": 3}}} in result


def test_build_filters_terms_languages():
    result = build_filters(SearchFilters(semantic_query="x", languages_required=["Python", "Go"]))
    assert {"terms": {"languages_required": ["Python", "Go"]}} in result


def test_build_filters_multiple():
    result = build_filters(SearchFilters(semantic_query="x", seniority="senior", is_startup=True, min_review_score=3.5))
    assert len(result) == 3
```

- [ ] **Step 3: Run to verify they fail**

```bash
cd backend && uv run pytest tests/search/test_filters.py -v
```

Expected: FAIL.

- [ ] **Step 4: Create backend/backend/search/filters.py**

```python
from pydantic import BaseModel


class SearchFilters(BaseModel):
    is_consulting: bool | None = None
    is_startup: bool | None = None
    industry: str | None = None
    country: str | None = None
    employee_count: str | None = None
    min_review_score: float | None = None
    min_financial_health_score: int | None = None
    employment_type: str | None = None
    location_type: str | None = None
    seniority: str | None = None
    languages_required: list[str] | None = None
    semantic_query: str


def build_filters(filters: SearchFilters) -> list[dict]:
    clauses: list[dict] = []
    for field, value in {
        "is_consulting": filters.is_consulting,
        "is_startup": filters.is_startup,
        "industry": filters.industry,
        "country": filters.country,
        "employee_count": filters.employee_count,
        "employment_type": filters.employment_type,
        "location_type": filters.location_type,
        "seniority": filters.seniority,
    }.items():
        if value is not None:
            clauses.append({"term": {field: value}})
    if filters.min_review_score is not None:
        clauses.append({"range": {"review_score": {"gte": filters.min_review_score}}})
    if filters.min_financial_health_score is not None:
        clauses.append({"range": {"financial_health_score": {"gte": filters.min_financial_health_score}}})
    if filters.languages_required:
        clauses.append({"terms": {"languages_required": filters.languages_required}})
    return clauses
```

- [ ] **Step 5: Run to verify tests pass**

```bash
cd backend && uv run pytest tests/search/test_filters.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/backend/search/__init__.py backend/backend/search/filters.py backend/tests/search/__init__.py backend/tests/search/test_filters.py
git commit -m "feat(backend): add SearchFilters and build_filters"
```

---

### Task 10: Query understanding

**Files:**
- Create: `backend/backend/search/query_understanding.py`
- Create: `backend/tests/search/test_query_understanding.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/search/test_query_understanding.py`:

```python
import json
from unittest.mock import MagicMock
from backend.search.query_understanding import extract_filters, get_groq_client
from backend.search.filters import SearchFilters


def _mock_groq(response: dict) -> MagicMock:
    msg = MagicMock()
    msg.content = json.dumps(response)
    choice = MagicMock()
    choice.message = msg
    completion = MagicMock()
    completion.choices = [choice]
    client = MagicMock()
    client.chat.completions.create.return_value = completion
    return client


async def test_returns_search_filters():
    groq = _mock_groq({"semantic_query": "senior python remote", "seniority": "senior", "location_type": "remote"})
    result = await extract_filters(groq, cv_text="5yr Python", query="senior python remote")
    assert isinstance(result, SearchFilters)
    assert result.semantic_query == "senior python remote"
    assert result.seniority == "senior"
    assert result.location_type == "remote"


async def test_uses_json_mode():
    groq = _mock_groq({"semantic_query": "engineer"})
    await extract_filters(groq, cv_text="cv", query="q")
    kwargs = groq.chat.completions.create.call_args.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}


async def test_falls_back_to_query_when_semantic_query_missing():
    groq = _mock_groq({})
    result = await extract_filters(groq, cv_text="cv", query="fallback query")
    assert result.semantic_query == "fallback query"


def test_get_groq_client(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    assert get_groq_client() is not None
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && uv run pytest tests/search/test_query_understanding.py -v
```

Expected: FAIL.

- [ ] **Step 3: Create backend/backend/search/query_understanding.py**

```python
import json
import os
from groq import Groq
from backend.search.filters import SearchFilters

_SYSTEM_PROMPT = """Extract structured search filters and a semantic query from a CV and job search query.
Return a JSON object with exactly these fields (null for unknown):
{
  "semantic_query": "required — keyword-rich string combining CV skills and job intent",
  "is_consulting": boolean or null,
  "is_startup": boolean or null,
  "industry": "string or null",
  "country": "string or null",
  "employee_count": "string or null",
  "min_review_score": number or null,
  "min_financial_health_score": integer or null,
  "employment_type": "full-time|part-time|contract|internship|stage|freelance or null",
  "location_type": "on-site|remote|hybrid or null",
  "seniority": "junior|mid|senior|lead|principal|staff|director or null",
  "languages_required": ["list"] or null
}"""


def get_groq_client() -> Groq:
    return Groq(api_key=os.environ["GROQ_API_KEY"])


async def extract_filters(client: Groq, cv_text: str, query: str) -> SearchFilters:
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"CV:\n{cv_text}\n\nSearch query:\n{query}"},
        ],
        response_format={"type": "json_object"},
    )
    data = json.loads(response.choices[0].message.content)
    data.setdefault("semantic_query", query)
    valid_fields = SearchFilters.model_fields.keys()
    return SearchFilters(**{k: v for k, v in data.items() if k in valid_fields})
```

- [ ] **Step 4: Run to verify tests pass**

```bash
cd backend && uv run pytest tests/search/test_query_understanding.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/backend/search/query_understanding.py backend/tests/search/test_query_understanding.py
git commit -m "feat(backend): add query understanding via Groq"
```

---

### Task 11: Models lifecycle

**Files:**
- Create: `backend/backend/search/models_lifecycle.py`
- Create: `backend/tests/search/test_models_lifecycle.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/search/test_models_lifecycle.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
import backend.search.models_lifecycle as m
from backend.search.models_lifecycle import get_biencoder, get_reranker, init_models


def test_get_biencoder_raises_before_init():
    m._biencoder = None
    with pytest.raises(AssertionError):
        get_biencoder()


def test_get_reranker_raises_before_init():
    m._reranker = None
    with pytest.raises(AssertionError):
        get_reranker()


def test_init_models_sets_both():
    m._biencoder = None
    m._reranker = None
    mock_st = MagicMock()
    mock_ce = MagicMock()
    with patch("backend.search.models_lifecycle.SentenceTransformer", return_value=mock_st), \
         patch("backend.search.models_lifecycle.CrossEncoder", return_value=mock_ce):
        init_models()
    assert get_biencoder() is mock_st
    assert get_reranker() is mock_ce
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && uv run pytest tests/search/test_models_lifecycle.py -v
```

Expected: FAIL.

- [ ] **Step 3: Create backend/backend/search/models_lifecycle.py**

```python
from sentence_transformers import SentenceTransformer
from sentence_transformers.cross_encoder import CrossEncoder

_biencoder: SentenceTransformer | None = None
_reranker: CrossEncoder | None = None


def init_models() -> None:
    global _biencoder, _reranker
    _biencoder = SentenceTransformer("BAAI/bge-small-en-v1.5")
    _reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")


def get_biencoder() -> SentenceTransformer:
    assert _biencoder is not None, "models not initialized"
    return _biencoder


def get_reranker() -> CrossEncoder:
    assert _reranker is not None, "models not initialized"
    return _reranker
```

- [ ] **Step 4: Run to verify tests pass**

```bash
cd backend && uv run pytest tests/search/test_models_lifecycle.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/backend/search/models_lifecycle.py backend/tests/search/test_models_lifecycle.py
git commit -m "feat(backend): add model lifecycle for biencoder and cross-encoder"
```

---

### Task 12: Retrieval module

**Files:**
- Create: `backend/backend/search/retrieval.py`
- Create: `backend/tests/search/test_retrieval.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/search/test_retrieval.py`:

```python
from unittest.mock import AsyncMock
from backend.search.retrieval import build_hybrid_query, hybrid_retrieve
from backend.search.filters import SearchFilters
from backend.opensearch_client import PIPELINE_NAME


def test_build_hybrid_query_has_two_legs():
    q = build_hybrid_query("python", [0.1] * 384, SearchFilters(semantic_query="python"))
    legs = q["query"]["hybrid"]["queries"]
    assert len(legs) == 2
    assert "match" in legs[0]["bool"]["must"]
    assert "knn" in legs[1]["bool"]["must"]
    assert q["size"] == 50


def test_build_hybrid_query_applies_filters_to_both_legs():
    f = SearchFilters(semantic_query="x", seniority="senior", is_consulting=False)
    q = build_hybrid_query("x", [0.0] * 384, f)
    for leg in q["query"]["hybrid"]["queries"]:
        assert len(leg["bool"]["filter"]) == 2


async def test_hybrid_retrieve_uses_pipeline():
    mock_os = AsyncMock()
    mock_os.search.return_value = {"hits": {"hits": [{"_source": {"job_id": "abc"}}]}}
    result = await hybrid_retrieve(mock_os, [0.1] * 384, SearchFilters(semantic_query="python"))
    kwargs = mock_os.search.call_args.kwargs
    assert kwargs["params"]["search_pipeline"] == PIPELINE_NAME
    assert result == [{"_source": {"job_id": "abc"}}]
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && uv run pytest tests/search/test_retrieval.py -v
```

Expected: FAIL.

- [ ] **Step 3: Create backend/backend/search/retrieval.py**

```python
from opensearchpy import AsyncOpenSearch
from backend.opensearch_client import INDEX_NAME, PIPELINE_NAME
from backend.search.filters import SearchFilters, build_filters


def build_hybrid_query(
    semantic_query: str,
    query_embedding: list[float],
    filters: SearchFilters,
    size: int = 50,
) -> dict:
    filter_clauses = build_filters(filters)
    return {
        "query": {
            "hybrid": {
                "queries": [
                    {
                        "bool": {
                            "must": {"match": {"description": semantic_query}},
                            "filter": filter_clauses,
                        }
                    },
                    {
                        "bool": {
                            "must": {"knn": {"embedding": {"vector": query_embedding, "k": 100}}},
                            "filter": filter_clauses,
                        }
                    },
                ]
            }
        },
        "size": size,
    }


async def hybrid_retrieve(
    client: AsyncOpenSearch,
    query_embedding: list[float],
    filters: SearchFilters,
) -> list[dict]:
    query = build_hybrid_query(filters.semantic_query, query_embedding, filters)
    response = await client.search(
        index=INDEX_NAME,
        body=query,
        params={"search_pipeline": PIPELINE_NAME},
    )
    return response["hits"]["hits"]
```

- [ ] **Step 4: Run to verify tests pass**

```bash
cd backend && uv run pytest tests/search/test_retrieval.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/backend/search/retrieval.py backend/tests/search/test_retrieval.py
git commit -m "feat(backend): add OpenSearch hybrid retrieval"
```

---

### Task 13: Reranker module

**Files:**
- Create: `backend/backend/search/reranker.py`
- Create: `backend/tests/search/test_reranker.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/search/test_reranker.py`:

```python
from unittest.mock import MagicMock
from backend.search.reranker import rerank


def _hit(job_id: str, summary_text: str = "") -> dict:
    return {"_source": {"job_id": job_id, "summary_text": summary_text}}


def test_sorts_by_score_descending():
    reranker = MagicMock()
    reranker.predict.return_value = [0.2, 0.9, 0.5]
    result = rerank(reranker, [_hit("a"), _hit("b"), _hit("c")], "python")
    assert [h["_source"]["job_id"] for h in result] == ["b", "c", "a"]


def test_respects_top_k():
    reranker = MagicMock()
    reranker.predict.return_value = list(range(30))
    result = rerank(reranker, [_hit(str(i)) for i in range(30)], "x", top_k=20)
    assert len(result) == 20


def test_falls_back_to_empty_string_for_missing_summary():
    reranker = MagicMock()
    reranker.predict.return_value = [0.1]
    rerank(reranker, [{"_source": {"job_id": "a"}}], "x")
    pairs = reranker.predict.call_args[0][0]
    assert pairs[0][1] == ""


def test_builds_correct_pairs():
    reranker = MagicMock()
    reranker.predict.return_value = [0.5]
    rerank(reranker, [_hit("a", "ml engineer")], "python ml")
    assert reranker.predict.call_args[0][0] == [("python ml", "ml engineer")]
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && uv run pytest tests/search/test_reranker.py -v
```

Expected: FAIL.

- [ ] **Step 3: Create backend/backend/search/reranker.py**

```python
from sentence_transformers.cross_encoder import CrossEncoder


def rerank(
    reranker: CrossEncoder,
    hits: list[dict],
    semantic_query: str,
    top_k: int = 20,
) -> list[dict]:
    pairs = [(semantic_query, hit["_source"].get("summary_text") or "") for hit in hits]
    scores = reranker.predict(pairs)
    ranked = sorted(zip(hits, scores), key=lambda x: x[1], reverse=True)
    return [hit for hit, _ in ranked[:top_k]]
```

- [ ] **Step 4: Run to verify tests pass**

```bash
cd backend && uv run pytest tests/search/test_reranker.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/backend/search/reranker.py backend/tests/search/test_reranker.py
git commit -m "feat(backend): add cross-encoder reranker"
```

---

### Task 14: Outbox worker

**Files:**
- Create: `backend/backend/outbox/__init__.py` (empty)
- Create: `backend/backend/outbox/worker.py`
- Create: `backend/tests/test_outbox_worker.py`

- [ ] **Step 1: Create empty `__init__.py`**

```bash
touch backend/backend/outbox/__init__.py
```

- [ ] **Step 2: Write failing tests**

Create `backend/tests/test_outbox_worker.py`:

```python
from unittest.mock import AsyncMock
from sqlalchemy import select
from backend.models import Outbox, Job, Company
from backend.outbox.worker import process_pending_events


async def _company(session, name="Acme") -> Company:
    c = Company(name=name)
    session.add(c)
    await session.flush()
    return c


async def _job(session, company_id, url="https://ex.com/1") -> Job:
    j = Job(url=url, title="Engineer", company_id=company_id)
    session.add(j)
    await session.flush()
    return j


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


async def test_company_event_calls_update_by_query(db_session):
    company = await _company(db_session, "TestCo")
    db_session.add(Outbox(event_type="company_upserted", entity_id=company.id, payload={}))
    await db_session.commit()

    mock_os = AsyncMock()
    await process_pending_events(db_session, mock_os)

    mock_os.update_by_query.assert_called_once()
    result = await db_session.execute(select(Outbox))
    assert result.scalar_one().processed_at is not None


async def test_opensearch_failure_leaves_event_unprocessed(db_session):
    company = await _company(db_session, "FailCo")
    job = await _job(db_session, company.id, "https://ex.com/fail")
    db_session.add(Outbox(event_type="job_upserted", entity_id=job.id, payload={}))
    await db_session.commit()

    mock_os = AsyncMock()
    mock_os.index.side_effect = Exception("OpenSearch down")
    await process_pending_events(db_session, mock_os)

    result = await db_session.execute(select(Outbox))
    assert result.scalar_one().processed_at is None
```

- [ ] **Step 3: Run to verify they fail**

```bash
cd backend && uv run pytest tests/test_outbox_worker.py -v
```

Expected: FAIL.

- [ ] **Step 4: Create backend/backend/outbox/worker.py**

```python
import asyncio
import logging
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from opensearchpy import AsyncOpenSearch

from backend.database import get_session_factory
from backend.models import Outbox, Job, Company
from backend.opensearch_client import get_opensearch, INDEX_NAME

logger = logging.getLogger(__name__)


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
    }


async def _handle_job_upserted(event: Outbox, session: AsyncSession, os_client: AsyncOpenSearch) -> None:
    result = await session.execute(
        select(Job).options(selectinload(Job.company)).where(Job.id == event.entity_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        return
    doc = _build_job_doc(job, event.payload.get("embedding"))
    await os_client.index(index=INDEX_NAME, id=str(job.id), body=doc)


async def _handle_company_upserted(event: Outbox, session: AsyncSession, os_client: AsyncOpenSearch) -> None:
    result = await session.execute(select(Company).where(Company.id == event.entity_id))
    company = result.scalar_one_or_none()
    if company is None:
        return
    await os_client.update_by_query(
        index=INDEX_NAME,
        body={
            "script": {
                "source": (
                    "ctx._source.is_consulting = params.is_consulting;"
                    "ctx._source.is_startup = params.is_startup;"
                    "ctx._source.industry = params.industry;"
                    "ctx._source.country = params.country;"
                    "ctx._source.review_score = params.review_score;"
                    "ctx._source.financial_health_score = params.financial_health_score;"
                ),
                "params": {
                    "is_consulting": company.is_consulting,
                    "is_startup": company.is_startup,
                    "industry": company.industry,
                    "country": company.country,
                    "review_score": company.review_score,
                    "financial_health_score": company.financial_health_score,
                },
            },
            "query": {"term": {"company_id": str(company.id)}},
        },
    )


async def process_pending_events(session: AsyncSession, os_client: AsyncOpenSearch) -> None:
    result = await session.execute(
        select(Outbox)
        .where(Outbox.processed_at.is_(None))
        .order_by(Outbox.created_at)
        .limit(100)
    )
    events = result.scalars().all()
    for event in events:
        try:
            if event.event_type == "job_upserted":
                await _handle_job_upserted(event, session, os_client)
            elif event.event_type == "company_upserted":
                await _handle_company_upserted(event, session, os_client)
            event.processed_at = datetime.now(timezone.utc)
        except Exception as e:
            logger.warning("Outbox event %s failed: %s", event.id, e)
    if events:
        await session.commit()


async def outbox_worker() -> None:
    factory = get_session_factory()
    while True:
        try:
            os_client = get_opensearch()
            async with factory() as session:
                await process_pending_events(session, os_client)
        except Exception as e:
            logger.warning("Outbox worker error: %s", e)
        await asyncio.sleep(1)
```

- [ ] **Step 5: Run to verify tests pass**

```bash
cd backend && uv run pytest tests/test_outbox_worker.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/backend/outbox/__init__.py backend/backend/outbox/worker.py backend/tests/test_outbox_worker.py
git commit -m "feat(backend): add outbox worker for Postgres→OpenSearch sync"
```

---

### Task 15: Search router

**Files:**
- Create: `backend/backend/routers/search.py`
- Create: `backend/tests/search/test_search_endpoint.py`

- [ ] **Step 1: Create backend/backend/routers/search.py**

```python
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from sentence_transformers import SentenceTransformer
from sentence_transformers.cross_encoder import CrossEncoder
from opensearchpy import AsyncOpenSearch
from pydantic import BaseModel
from groq import Groq

from backend.database import get_session
from backend.models import Job
from backend.schemas import JobSearchResponse
from backend.search.filters import SearchFilters
from backend.search.models_lifecycle import get_biencoder, get_reranker
from backend.search.query_understanding import extract_filters, get_groq_client
from backend.search.retrieval import hybrid_retrieve
from backend.search.reranker import rerank
from backend.opensearch_client import get_opensearch

router = APIRouter(prefix="/jobs", tags=["search"])


class SearchRequest(BaseModel):
    cv_text: str
    query: str


@router.post("/search", response_model=list[JobSearchResponse])
async def search_jobs(
    body: SearchRequest,
    session: AsyncSession = Depends(get_session),
    biencoder: SentenceTransformer = Depends(get_biencoder),
    reranker: CrossEncoder = Depends(get_reranker),
    groq_client: Groq = Depends(get_groq_client),
    os_client: AsyncOpenSearch = Depends(get_opensearch),
) -> list[JobSearchResponse]:
    filters: SearchFilters = await extract_filters(groq_client, body.cv_text, body.query)
    query_embedding: list[float] = biencoder.encode(filters.semantic_query).tolist()
    hits = await hybrid_retrieve(os_client, query_embedding, filters)
    ranked_hits = rerank(reranker, hits, filters.semantic_query)

    if not ranked_hits:
        return []

    ranked_ids = [hit["_source"]["job_id"] for hit in ranked_hits]
    result = await session.execute(
        select(Job).options(selectinload(Job.company)).where(Job.id.in_(ranked_ids))
    )
    jobs_by_id = {str(job.id): job for job in result.scalars()}
    return [jobs_by_id[id_] for id_ in ranked_ids if id_ in jobs_by_id]
```

- [ ] **Step 2: Write failing tests**

Create `backend/tests/search/test_search_endpoint.py`:

```python
import uuid
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.main import app
from backend.database import get_session
from backend.search.models_lifecycle import get_biencoder, get_reranker
from backend.search.query_understanding import get_groq_client
from backend.opensearch_client import get_opensearch
from backend.models import Company, Job


def _mock_groq(semantic_query: str = "python engineer") -> MagicMock:
    msg = MagicMock()
    msg.content = json.dumps({"semantic_query": semantic_query})
    choice = MagicMock()
    choice.message = msg
    completion = MagicMock()
    completion.choices = [choice]
    client = MagicMock()
    client.chat.completions.create.return_value = completion
    return client


@pytest_asyncio.fixture
async def search_client(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():
        async with factory() as session:
            yield session

    mock_biencoder = MagicMock()
    mock_biencoder.encode.return_value = [0.0] * 384
    mock_reranker = MagicMock()
    mock_reranker.predict.return_value = [0.9]
    mock_os = AsyncMock()

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_biencoder] = lambda: mock_biencoder
    app.dependency_overrides[get_reranker] = lambda: mock_reranker
    app.dependency_overrides[get_groq_client] = lambda: _mock_groq()
    app.dependency_overrides[get_opensearch] = lambda: mock_os

    with patch("backend.main.init_models"), \
         patch("backend.main.init_opensearch", new_callable=AsyncMock), \
         patch("backend.main.outbox_worker", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac, mock_os, factory

    app.dependency_overrides.clear()


async def test_search_returns_200_with_ranked_jobs(search_client):
    ac, mock_os, factory = search_client
    job_id = uuid.uuid4()

    async with factory() as session:
        company = Company(name="acme")
        session.add(company)
        await session.flush()
        session.add(Job(id=job_id, url="https://ex.com/1", title="ML Engineer", company_id=company.id))
        await session.commit()

    mock_os.search.return_value = {
        "hits": {"hits": [{"_source": {"job_id": str(job_id), "summary_text": "ml engineer"}}]}
    }

    resp = await ac.post("/jobs/search", json={"cv_text": "5yr Python", "query": "ml engineer"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == str(job_id)
    assert "company" in data[0]
    assert data[0]["company"]["name"] == "acme"


async def test_search_returns_empty_list_when_no_hits(search_client):
    ac, mock_os, _ = search_client
    mock_os.search.return_value = {"hits": {"hits": []}}
    resp = await ac.post("/jobs/search", json={"cv_text": "cv", "query": "q"})
    assert resp.status_code == 200
    assert resp.json() == []
```

- [ ] **Step 3: Run to verify tests fail**

```bash
cd backend && uv run pytest tests/search/test_search_endpoint.py -v
```

Expected: FAIL — router not registered yet.

- [ ] **Step 4: Commit router before wiring**

```bash
git add backend/backend/routers/search.py backend/tests/search/test_search_endpoint.py
git commit -m "feat(backend): add search router (not yet wired)"
```

---

### Task 16: Wire everything into main.py

**Files:**
- Modify: `backend/backend/main.py`

- [ ] **Step 1: Replace main.py**

```python
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.routers import companies, jobs
from backend.routers.search import router as search_router
from backend.search.models_lifecycle import init_models
from backend.opensearch_client import init_opensearch
from backend.outbox.worker import outbox_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_models()
    await init_opensearch()
    task = asyncio.create_task(outbox_worker())
    yield
    task.cancel()


app = FastAPI(title="jobstrainer backend", lifespan=lifespan)
app.include_router(companies.router)
app.include_router(jobs.router)
app.include_router(search_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    import traceback
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"detail": "internal server error"})
```

- [ ] **Step 2: Run search endpoint tests**

```bash
cd backend && uv run pytest tests/search/test_search_endpoint.py -v
```

Expected: all PASS.

- [ ] **Step 3: Run all backend tests**

```bash
cd backend && uv run pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/backend/main.py
git commit -m "feat(backend): wire search router, models, OpenSearch, and outbox worker"
```

---

### Task 17: Ingestion embedder

**Files:**
- Modify: `ingestion/pyproject.toml`
- Create: `ingestion/ingestion/embedder.py`
- Create: `ingestion/tests/test_embedder.py`

- [ ] **Step 1: Add sentence-transformers to ingestion/pyproject.toml**

```toml
[project]
name = "ingestion"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "beautifulsoup4>=4.14.3",
    "ddgs>=9.14.1",
    "ftfy>=6.3.1",
    "groq>=1.2.0",
    "playwright>=1.58.0",
    "pydantic>=2.13.2",
    "pyperclip>=1.11.0",
    "python-dotenv>=1.2.2",
    "python-jobspy>=1.1.82",
    "requests>=2.33.1",
    "sentence-transformers>=3.0.0",
    "tabulate>=0.10.0",
    "trafilatura>=2.0.0",
    "tqdm>=4.67.3",
]

[dependency-groups]
dev = [
    "pytest>=9.0.3",
]
```

- [ ] **Step 2: Update the lock file**

```bash
uv lock
```

- [ ] **Step 3: Write failing tests**

Create `ingestion/tests/test_embedder.py`:

```python
import numpy as np
from unittest.mock import MagicMock, patch
from ingestion.embedder import embed, _summary_text
from ingestion.offer.models import OfferSummary


def test_summary_text_joins_all_fields():
    s = OfferSummary(role_info=["senior engineer"], requirements=["Python"], responsibilities=["train models"], domain=["NLP"])
    result = _summary_text(s)
    assert "senior engineer" in result
    assert "Python" in result
    assert "train models" in result
    assert "NLP" in result


def test_embed_none_for_none_summary():
    assert embed("title", None) is None


def test_embed_none_for_empty_summary():
    assert embed("title", OfferSummary()) is None


def test_embed_returns_list_of_floats():
    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([0.1] * 384)
    with patch("ingestion.embedder.get_embedder", return_value=mock_model):
        result = embed("ML Engineer", OfferSummary(role_info=["builds ML models"]))
    assert isinstance(result, list)
    assert len(result) == 384


def test_embed_includes_title_in_input():
    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([0.0] * 384)
    with patch("ingestion.embedder.get_embedder", return_value=mock_model):
        embed("Data Scientist", OfferSummary(role_info=["NLP researcher"]))
    text_arg = mock_model.encode.call_args[0][0]
    assert text_arg.startswith("Data Scientist\n")
    assert "NLP researcher" in text_arg
```

- [ ] **Step 4: Run to verify they fail**

```bash
cd ingestion && uv run pytest tests/test_embedder.py -v
```

Expected: FAIL.

- [ ] **Step 5: Create ingestion/ingestion/embedder.py**

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

- [ ] **Step 6: Run to verify tests pass**

```bash
cd ingestion && uv run pytest tests/test_embedder.py -v
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add ingestion/pyproject.toml uv.lock ingestion/ingestion/embedder.py ingestion/tests/test_embedder.py
git commit -m "feat(ingestion): add bge embedder on summary"
```

---

### Task 18: Ingestion pipeline integration

**Files:**
- Modify: `ingestion/ingestion/client.py`
- Modify: `ingestion/ingestion/pipeline/__main__.py`
- Modify: `ingestion/tests/pipeline/test_client.py`

- [ ] **Step 1: Write failing tests**

Add to `ingestion/tests/pipeline/test_client.py`:

```python
def test_post_job_includes_embedding_when_provided():
    with patch("ingestion.client.requests.post") as mock_post:
        mock_post.return_value = _resp(201, {"id": "abc"})
        post_job(_offer(), embedding=[0.1, 0.2, 0.3])
    assert mock_post.call_args.kwargs["json"]["embedding"] == [0.1, 0.2, 0.3]


def test_post_job_omits_embedding_when_none():
    with patch("ingestion.client.requests.post") as mock_post:
        mock_post.return_value = _resp(201, {"id": "abc"})
        post_job(_offer(), embedding=None)
    assert "embedding" not in mock_post.call_args.kwargs["json"]
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd ingestion && uv run pytest tests/pipeline/test_client.py::test_post_job_includes_embedding_when_provided tests/pipeline/test_client.py::test_post_job_omits_embedding_when_none -v
```

Expected: FAIL.

- [ ] **Step 3: Replace ingestion/ingestion/client.py**

```python
import os
import requests
from ingestion.offer.models import EnrichedOffer


def _base() -> str:
    url = os.environ.get("BACKEND_URL")
    if not url:
        raise RuntimeError("BACKEND_URL environment variable is not set")
    return url.rstrip("/")


def post_job(offer: EnrichedOffer, embedding: list[float] | None = None) -> tuple[int, dict]:
    payload = offer.model_dump(mode="json")
    payload["company_name"] = payload.pop("company")
    if embedding is not None:
        payload["embedding"] = embedding
    resp = requests.post(f"{_base()}/jobs/", json=payload, timeout=30)
    if not resp.ok:
        raise requests.HTTPError(f"{resp.status_code} — {resp.text}", response=resp)
    return resp.status_code, resp.json()


def post_company(data: dict) -> tuple[int, dict]:
    resp = requests.post(f"{_base()}/companies/", json=data, timeout=30)
    if not resp.ok:
        raise requests.HTTPError(f"{resp.status_code} — {resp.text}", response=resp)
    return resp.status_code, resp.json()
```

- [ ] **Step 4: Run all client tests**

```bash
cd ingestion && uv run pytest tests/pipeline/test_client.py -v
```

Expected: all PASS.

- [ ] **Step 5: Replace ingestion/ingestion/pipeline/__main__.py**

```python
import argparse
import os
from groq import Groq
from ingestion.offer.offer import enrich_all
from ingestion.company.company import enrich as enrich_company
from ingestion.client import post_job, post_company
from ingestion.embedder import embed

_IDENTITY_FIELDS = {"id", "name", "created_at", "updated_at"}


def is_enrichment_needed(company: dict) -> bool:
    enrichable = {k: v for k, v in company.items() if k not in _IDENTITY_FIELDS}
    values = list(enrichable.values())
    if not values:
        return False
    return sum(1 for v in values if v is None) >= len(values) / 2


def run(query: str, hours: int) -> None:
    groq = Groq(api_key=os.environ["GROQ_API_KEY"])

    print(f"Scraping offers: {query!r}, last {hours}h")
    offers = enrich_all(query, hours, groq)
    print(f"Scraped {len(offers)} offers")

    new_jobs = 0
    errors = 0
    company_locations: dict[str, str] = {}
    for offer in offers:
        try:
            embedding = embed(offer.title, offer.summary)
            status, _ = post_job(offer, embedding=embedding)
            if status == 201:
                new_jobs += 1
        except Exception as e:
            print(f"[warn] Failed to post job {offer.url!r}: {e}")
            errors += 1
            continue
        if offer.company not in company_locations or (
            company_locations[offer.company] == "" and offer.location
        ):
            company_locations[offer.company] = offer.location or ""
    print(f"Jobs: {new_jobs} new, {len(offers) - new_jobs - errors} existing, {errors} errors")

    enriched = 0
    new_companies = 0
    for name, location in company_locations.items():
        try:
            status, record = post_company({"name": name})
        except Exception as e:
            print(f"[warn] Failed to upsert company {name!r}: {e}")
            continue
        if status == 201:
            new_companies += 1
        if is_enrichment_needed(record):
            try:
                profile, _ = enrich_company(name, location, groq)
                post_company(profile.model_dump(mode="json"))
                enriched += 1
            except Exception as e:
                print(f"[warn] Failed to enrich company {name!r}: {e}")
    print(f"Companies: {new_companies} new, {enriched} enriched out of {len(company_locations)} unique")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest offers and companies into backend")
    parser.add_argument("query", help="Job search query")
    parser.add_argument("--hours", type=int, default=72, help="How many hours back to search")
    args = parser.parse_args()
    run(args.query, args.hours)


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run all ingestion tests**

```bash
cd ingestion && uv run pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add ingestion/ingestion/client.py ingestion/ingestion/pipeline/__main__.py ingestion/tests/pipeline/test_client.py
git commit -m "feat(ingestion): integrate embedder into pipeline"
```

---

### Task 19: Dockerfiles — pre-download models

**Files:**
- Modify: `ingestion/Dockerfile`
- Modify: `backend/Dockerfile`

- [ ] **Step 1: Replace ingestion/Dockerfile**

```dockerfile
FROM python:3.13

WORKDIR /app

RUN pip install uv --quiet

COPY pyproject.toml uv.lock ./
COPY ingestion/pyproject.toml ./ingestion/pyproject.toml

RUN uv sync --package ingestion --no-dev

RUN uv run playwright install chromium && \
    uv run playwright install-deps chromium

RUN uv run python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"

COPY ingestion/ ./ingestion/

WORKDIR /app/ingestion

CMD ["sh", "-c", "if [ -z \"$OFFER_QUERY\" ]; then echo 'ERROR: OFFER_QUERY is not set' >&2; exit 1; fi; while true; do uv run python -m ingestion.pipeline \"$OFFER_QUERY\" --hours 2; sleep 7200; done"]
```

- [ ] **Step 2: Replace backend/Dockerfile**

```dockerfile
FROM python:3.13-slim

WORKDIR /app

RUN pip install uv --quiet

COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml ./backend/pyproject.toml

RUN uv sync --package backend --no-dev

RUN uv run python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"
RUN uv run python -c "from sentence_transformers.cross_encoder import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

COPY backend/ ./backend/

WORKDIR /app/backend

EXPOSE 8000

CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
```

- [ ] **Step 3: Commit**

```bash
git add ingestion/Dockerfile backend/Dockerfile
git commit -m "feat(docker): pre-download ML models at image build time"
```
