# Tailorer Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the LangGraph-powered job application agent, WebSocket API, applicant profile storage, and DB migrations that form the backend of the Tailorer feature.

**Architecture:** A LangGraph `StateGraph` drives the application flow (navigate → tailor → fill → confirm → next page). Every agent↔extension exchange uses `interrupt()` — the graph suspends, the WS handler forwards the payload to the extension, waits for the response, and resumes with `Command(resume=...)`. No asyncio queues needed.

**Tech Stack:** LangGraph + `langchain-groq` (`ChatGroq`), `langgraph-checkpoint-postgres` (`AsyncPostgresSaver`), FastAPI WebSocket, SQLAlchemy async, Alembic, Groq API, `python-docx`.

**Spec:** `docs/superpowers/specs/2026-05-28-tailorer-design.md`

**Note:** This is Plan 1 of 2. Plan 2 covers the browser extension.

---

## File Map

**New files:**
- `backend/backend/tailorer/__init__.py`
- `backend/backend/tailorer/models.py` — `ApplicantProfile`, `Application` ORM
- `backend/backend/tailorer/schemas.py` — Pydantic request/response models
- `backend/backend/tailorer/tailor.py` — CV + cover letter generation via Groq
- `backend/backend/tailorer/nodes.py` — all LangGraph node functions
- `backend/backend/tailorer/agent.py` — `StateGraph` construction + `TailorerState`
- `backend/backend/tailorer/router.py` — REST endpoints + WebSocket endpoint
- `backend/alembic/versions/007_applicant_profile.py`
- `backend/alembic/versions/008_applications.py`
- `backend/tests/tailorer/__init__.py`
- `backend/tests/tailorer/test_profile.py`
- `backend/tests/tailorer/test_tailor.py`
- `backend/tests/tailorer/test_nodes.py`
- `backend/tests/tailorer/test_ws.py`

**Modified files:**
- `backend/pyproject.toml` — add langgraph deps
- `backend/backend/models.py` — remove `cv_text` from `User`
- `backend/backend/routers/cv.py` — read/write `ApplicantProfile.cv_text`
- `backend/backend/routers/search.py` — get `cv_text` from profile
- `backend/backend/main.py` — register tailorer router, `checkpointer.setup()`
- `backend/tests/conftest.py` — import tailorer models so they register with `Base`
- `frontend/src/components/JobCard.tsx` — write `localStorage.tailorer_pending` on link click

---

## Task 1: Add dependencies

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add new deps to pyproject.toml**

In `backend/pyproject.toml`, add to the `dependencies` list:
```toml
"langgraph>=0.3.0",
"langchain-groq>=0.3.0",
"langchain-core>=0.3.0",
"langgraph-checkpoint-postgres>=2.0.0",
"psycopg[binary,pool]>=3.2.0",
```

- [ ] **Step 2: Install**

```bash
cd backend && uv sync
```

Expected: no errors, `uv.lock` updated.

- [ ] **Step 3: Commit**

```bash
git add backend/pyproject.toml uv.lock
git commit -m "chore(tailorer): add langgraph + psycopg dependencies"
```

---

## Task 2: Migration 007 — applicant_profile

**Files:**
- Create: `backend/alembic/versions/007_applicant_profile.py`

- [ ] **Step 1: Create migration file**

```python
# backend/alembic/versions/007_applicant_profile.py
"""add applicant_profile table

Revision ID: 007
Revises: 006
Create Date: 2026-05-28
"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "applicant_profile",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("work_auth", sa.Text(), nullable=True),
        sa.Column("urls", postgresql.JSONB(), nullable=True),
        sa.Column("extra_qa", postgresql.JSONB(), nullable=True),
        sa.Column("cv_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_applicant_profile_user_id"),
    )
    # Migrate existing cv_text from users
    op.execute("""
        INSERT INTO applicant_profile (user_id, cv_text, created_at, updated_at)
        SELECT id, cv_text, now(), now()
        FROM users
        WHERE cv_text IS NOT NULL
    """)
    op.drop_column("users", "cv_text")


def downgrade() -> None:
    op.add_column("users", sa.Column("cv_text", sa.Text(), nullable=True))
    op.execute("""
        UPDATE users u
        SET cv_text = ap.cv_text
        FROM applicant_profile ap
        WHERE ap.user_id = u.id
    """)
    op.drop_table("applicant_profile")
```

- [ ] **Step 2: Run migration against the dev DB**

```bash
cd backend && uv run alembic upgrade head
```

Expected: `Running upgrade 006 -> 007` with no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/007_applicant_profile.py
git commit -m "feat(tailorer): migration 007 — add applicant_profile, migrate cv_text"
```

---

## Task 3: Migration 008 — applications

**Files:**
- Create: `backend/alembic/versions/008_applications.py`

- [ ] **Step 1: Create migration file**

```python
# backend/alembic/versions/008_applications.py
"""add applications table

Revision ID: 008
Revises: 007
Create Date: 2026-05-28
"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "applications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="applied"),
        sa.CheckConstraint(
            "status IN ('applied','interviewing','rejected','offer')",
            name="ck_applications_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "job_id", name="uq_applications_user_job"),
    )


def downgrade() -> None:
    op.drop_table("applications")
```

- [ ] **Step 2: Run migration**

```bash
cd backend && uv run alembic upgrade head
```

Expected: `Running upgrade 007 -> 008` with no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/008_applications.py
git commit -m "feat(tailorer): migration 008 — add applications junction table"
```

---

## Task 4: ORM models + remove cv_text from User

**Files:**
- Create: `backend/backend/tailorer/__init__.py`
- Create: `backend/backend/tailorer/models.py`
- Modify: `backend/backend/models.py`

- [ ] **Step 1: Create `tailorer/__init__.py`**

```python
# backend/backend/tailorer/__init__.py
```

- [ ] **Step 2: Create `tailorer/models.py`**

```python
# backend/backend/tailorer/models.py
import uuid
from datetime import datetime
from sqlalchemy import Text, DateTime, ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.models import Base


class ApplicantProfile(Base):
    __tablename__ = "applicant_profile"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    first_name: Mapped[str | None] = mapped_column(Text)
    last_name: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    work_auth: Mapped[str | None] = mapped_column(Text)
    urls: Mapped[dict | None] = mapped_column(JSONB)
    extra_qa: Mapped[dict | None] = mapped_column(JSONB)
    cv_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_applications_user_job"),
        CheckConstraint("status IN ('applied','interviewing','rejected','offer')", name="ck_applications_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="applied")
```

- [ ] **Step 3: Remove `cv_text` from `User` in `backend/backend/models.py`**

Remove line 19 from `backend/backend/models.py`:
```python
    cv_text: Mapped[str | None] = mapped_column(Text)
```

- [ ] **Step 4: Update conftest to register new models with Base**

Add an import to `backend/tests/conftest.py` after the existing imports:
```python
import backend.backend.tailorer.models  # noqa: F401 — registers ApplicantProfile, Application with Base
```

- [ ] **Step 5: Verify test DB still creates cleanly**

```bash
cd backend && uv run pytest tests/test_auth.py -v
```

Expected: all auth tests pass (they depend on the users table).

- [ ] **Step 6: Commit**

```bash
git add backend/backend/tailorer/__init__.py backend/backend/tailorer/models.py backend/backend/models.py backend/tests/conftest.py
git commit -m "feat(tailorer): add ApplicantProfile + Application ORM models, drop User.cv_text"
```

---

## Task 5: Update cv router and search router to use ApplicantProfile

**Files:**
- Modify: `backend/backend/routers/cv.py`
- Modify: `backend/backend/routers/search.py`

- [ ] **Step 1: Rewrite `backend/backend/routers/cv.py`**

```python
import io
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from backend.database import get_session
from backend.models import User
from backend.tailorer.models import ApplicantProfile
from backend.auth.dependencies import get_current_user

router = APIRouter(prefix="/users", tags=["cv"])

_ALLOWED = {".pdf", ".docx", ".txt"}


def _extract_text(filename: str, content: bytes) -> str:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == ".pdf":
        import pdfplumber
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    if ext == ".docx":
        import docx
        doc = docx.Document(io.BytesIO(content))
        return "\n".join(p.text for p in doc.paragraphs)
    return content.decode("utf-8")


class CVResponse(BaseModel):
    cv_text: str | None
    has_cv: bool


class CVUploadResponse(BaseModel):
    message: str
    char_count: int


async def _get_or_create_profile(session: AsyncSession, user_id) -> ApplicantProfile:
    result = await session.execute(
        select(ApplicantProfile).where(ApplicantProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = ApplicantProfile(user_id=user_id)
        session.add(profile)
    return profile


@router.post("/cv", response_model=CVUploadResponse)
async def upload_cv(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    filename = file.filename or ""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _ALLOWED:
        raise HTTPException(status_code=400, detail="Unsupported file type. Upload PDF, DOCX, or TXT.")
    content = await file.read()
    text = _extract_text(filename, content)
    if not text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from file.")
    profile = await _get_or_create_profile(session, current_user.id)
    profile.cv_text = text
    session.add(profile)
    await session.commit()
    return CVUploadResponse(message="CV uploaded successfully", char_count=len(text))


@router.get("/cv", response_model=CVResponse)
async def get_cv(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    result = await session.execute(
        select(ApplicantProfile).where(ApplicantProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()
    cv_text = profile.cv_text if profile else None
    return CVResponse(cv_text=cv_text, has_cv=cv_text is not None)
```

- [ ] **Step 2: Update `backend/backend/routers/search.py` to load cv_text from profile**

Replace lines 42-47 (the cv_text check and extract_filters call) in `backend/backend/routers/search.py`:

```python
from sqlalchemy import select
# add at top with other imports:
from backend.tailorer.models import ApplicantProfile
```

Replace:
```python
    if not current_user.cv_text:
        raise HTTPException(status_code=400, detail="No CV uploaded. Please upload your CV first.")

    t0 = time.perf_counter()

    filters: SearchFilters = await extract_filters(groq_client, current_user.cv_text, body.query)
```

With:
```python
    profile_result = await session.execute(
        select(ApplicantProfile).where(ApplicantProfile.user_id == current_user.id)
    )
    profile = profile_result.scalar_one_or_none()
    if not profile or not profile.cv_text:
        raise HTTPException(status_code=400, detail="No CV uploaded. Please upload your CV first.")

    t0 = time.perf_counter()

    filters: SearchFilters = await extract_filters(groq_client, profile.cv_text, body.query)
```

- [ ] **Step 3: Run existing cv and search tests**

```bash
cd backend && uv run pytest tests/test_cv.py tests/search/test_search_endpoint.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add backend/backend/routers/cv.py backend/backend/routers/search.py
git commit -m "feat(tailorer): update cv router and search to use ApplicantProfile.cv_text"
```

---

## Task 6: Tailorer schemas

**Files:**
- Create: `backend/backend/tailorer/schemas.py`

- [ ] **Step 1: Write schemas**

```python
# backend/backend/tailorer/schemas.py
import uuid
from datetime import datetime
from pydantic import BaseModel


class ProfileUpsert(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    city: str | None = None
    country: str | None = None
    work_auth: str | None = None
    urls: dict | None = None
    extra_qa: dict | None = None


class ProfileResponse(ProfileUpsert):
    id: uuid.UUID
    user_id: uuid.UUID
    cv_text: str | None = None
    has_cv: bool
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_profile(cls, p) -> "ProfileResponse":
        return cls(
            id=p.id,
            user_id=p.user_id,
            first_name=p.first_name,
            last_name=p.last_name,
            email=p.email,
            phone=p.phone,
            city=p.city,
            country=p.country,
            work_auth=p.work_auth,
            urls=p.urls,
            extra_qa=p.extra_qa,
            cv_text=p.cv_text,
            has_cv=p.cv_text is not None,
            updated_at=p.updated_at,
        )
```

- [ ] **Step 2: Commit**

```bash
git add backend/backend/tailorer/schemas.py
git commit -m "feat(tailorer): add Pydantic schemas for profile"
```

---

## Task 7: Profile REST endpoints + tests

**Files:**
- Create: `backend/backend/tailorer/router.py` (profile endpoints only)
- Create: `backend/tests/tailorer/__init__.py`
- Create: `backend/tests/tailorer/test_profile.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/tailorer/test_profile.py
import pytest
from httpx import AsyncClient
from backend.auth.jwt import create_access_token


@pytest.fixture
async def auth_headers(client, db_session):
    from backend.models import User
    from passlib.context import CryptContext
    pwd = CryptContext(schemes=["bcrypt"])
    user = User(username="tester", password_hash=pwd.hash("pw"))
    db_session.add(user)
    await db_session.commit()
    token = create_access_token({"sub": str(user.id)})
    return {"Authorization": f"Bearer {token}"}


async def test_get_profile_empty(client: AsyncClient, auth_headers):
    r = await client.get("/tailorer/profile", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["first_name"] is None
    assert data["has_cv"] is False


async def test_upsert_profile(client: AsyncClient, auth_headers):
    payload = {
        "first_name": "Lorenzo",
        "last_name": "Schiroli",
        "email": "l@example.com",
        "phone": "+39123",
        "city": "Milan",
        "country": "Italy",
        "work_auth": "EU citizen",
        "urls": {"linkedin": "https://linkedin.com/in/test"},
        "extra_qa": {"notice_period": "2 weeks"},
    }
    r = await client.put("/tailorer/profile", headers=auth_headers, json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["first_name"] == "Lorenzo"
    assert data["last_name"] == "Schiroli"
    assert data["urls"]["linkedin"] == "https://linkedin.com/in/test"

    # Idempotent: second upsert updates
    r2 = await client.put("/tailorer/profile", headers=auth_headers,
                          json={**payload, "city": "Rome"})
    assert r2.status_code == 200
    assert r2.json()["city"] == "Rome"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/tailorer/test_profile.py -v
```

Expected: FAIL — `404 Not Found` (router not registered yet).

- [ ] **Step 3: Write profile endpoints in router.py**

```python
# backend/backend/tailorer/router.py
import uuid
from fastapi import APIRouter, Depends, HTTPException, WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models import User
from backend.tailorer.models import ApplicantProfile
from backend.tailorer.schemas import ProfileUpsert, ProfileResponse
from backend.auth.dependencies import get_current_user

router = APIRouter(prefix="/tailorer", tags=["tailorer"])


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    result = await session.execute(
        select(ApplicantProfile).where(ApplicantProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = ApplicantProfile(user_id=current_user.id)
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
    return ProfileResponse.from_profile(profile)


@router.put("/profile", response_model=ProfileResponse)
async def upsert_profile(
    body: ProfileUpsert,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    result = await session.execute(
        select(ApplicantProfile).where(ApplicantProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = ApplicantProfile(user_id=current_user.id)
        session.add(profile)
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(profile, field, val)
    await session.commit()
    await session.refresh(profile)
    return ProfileResponse.from_profile(profile)
```

- [ ] **Step 4: Register router in main.py (temporarily, to make tests pass)**

Add to `backend/backend/main.py`:
```python
from backend.tailorer.router import router as tailorer_router
# ... in the app setup:
app.include_router(tailorer_router)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/tailorer/test_profile.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/backend/tailorer/router.py backend/tests/tailorer/__init__.py backend/tests/tailorer/test_profile.py backend/backend/main.py
git commit -m "feat(tailorer): profile GET/PUT endpoints"
```

---

## Task 8: Tailor logic (CV + cover letter generation)

**Files:**
- Create: `backend/backend/tailorer/tailor.py`
- Create: `backend/tests/tailorer/test_tailor.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/tailorer/test_tailor.py
import pytest
from unittest.mock import MagicMock, patch


def _mock_groq_response(text: str):
    msg = MagicMock()
    msg.content = text
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def test_parse_cover_letter_response():
    from backend.tailorer.tailor import _parse_cover_letter_response
    raw = "COMPANY: Stripe\nPOSITION: ML Engineer\n---\nDear Hiring Manager,\n\nTest letter.\n\nKind regards,\nLorenzo"
    company, position, letter = _parse_cover_letter_response(raw)
    assert company == "Stripe"
    assert position == "ML Engineer"
    assert "Dear Hiring Manager" in letter


def test_build_cover_letter_docx_returns_bytes():
    from backend.tailorer.tailor import _build_docx_bytes
    data = _build_docx_bytes("Dear Hiring Manager,\n\nTest.\n\nKind regards,\nLorenzo")
    assert isinstance(data, bytes)
    assert len(data) > 0


def test_build_cv_docx_with_no_modifications():
    from backend.tailorer.tailor import _apply_cv_modifications
    import docx, io
    doc = docx.Document()
    doc.add_paragraph("Original text")
    buf = io.BytesIO()
    doc.save(buf)
    cv_bytes = buf.getvalue()
    result = _apply_cv_modifications(cv_bytes, [])
    assert isinstance(result, bytes)
    assert len(result) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/tailorer/test_tailor.py -v
```

Expected: FAIL — import error.

- [ ] **Step 3: Implement `tailor.py`**

```python
# backend/backend/tailorer/tailor.py
import io
import json
import os
import re
import shutil
import tempfile

import docx
from docx import Document
from groq import Groq

_LARGE = lambda: os.environ["GROQ_MODEL_LARGE"]


def _parse_cover_letter_response(raw: str) -> tuple[str, str, str]:
    import re
    company = re.search(r"^COMPANY:\s*(.+)$", raw, re.MULTILINE)
    position = re.search(r"^POSITION:\s*(.+)$", raw, re.MULTILINE)
    company = company.group(1).strip() if company else "company"
    position = position.group(1).strip() if position else "position"
    letter = raw.split("---", 1)[-1].strip()
    return company, position, letter


def _build_docx_bytes(text: str) -> bytes:
    doc = Document()
    for para in text.split("\n\n"):
        para = para.strip()
        if para:
            doc.add_paragraph(para)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _collapse(para, text: str) -> None:
    runs = para.runs
    if not runs:
        return
    runs[0].text = text
    for r in runs[1:]:
        r.text = ""


def _rm(para) -> None:
    para._element.getparent().remove(para._element)


def _apply_cv_modifications(cv_bytes: bytes, modifications: list[dict]) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        f.write(cv_bytes)
        tmp = f.name
    doc = Document(tmp)
    paragraphs = doc.paragraphs
    for mod in modifications:
        idx = mod.get("index")
        if idx is None or not (0 <= idx < len(paragraphs)):
            continue
        if mod["action"] == "replace":
            _collapse(paragraphs[idx], mod["text"])
        elif mod["action"] == "remove":
            _rm(paragraphs[idx])
    buf = io.BytesIO()
    doc.save(buf)
    import os as _os
    _os.unlink(tmp)
    return buf.getvalue()


async def generate_tailored_documents(
    cv_text: str,
    cv_bytes: bytes,
    job_description: str,
    groq_client: Groq,
) -> tuple[bytes, bytes, str]:
    """
    Returns: (tailored_cv_bytes, cover_letter_bytes, cover_letter_text)
    """
    # 1. Generate cover letter
    cl_prompt = (
        "You are an expert cover letter writer. "
        "Given the following CV and job description, produce exactly this structure:\n\n"
        "COMPANY: <hiring company name in 1-3 words max>\n"
        "POSITION: <job title in 3 words max>\n"
        "---\n"
        "<cover letter>\n\n"
        "Rules:\n"
        "- Email body format only (no subject line)\n"
        "- Greeting: 'Dear Hiring Manager,' if no name is known\n"
        "- 2-3 short paragraphs in formal business English\n"
        "- End with 'Kind regards,\\nLorenzo Schiroli'\n"
        "- No bullet points, no bold text, no placeholders\n\n"
        f"CV:\n{cv_text}\n\nJob Description:\n{job_description}"
    )
    cl_resp = groq_client.chat.completions.create(
        model=_LARGE(),
        messages=[{"role": "user", "content": cl_prompt}],
    )
    raw_cl = cl_resp.choices[0].message.content.strip()
    _, _, cl_text = _parse_cover_letter_response(raw_cl)
    cl_bytes = _build_docx_bytes(cl_text)

    # 2. Generate CV modifications
    para_list = "\n".join(
        f"{i}: {p.text}"
        for i, p in enumerate(Document(io.BytesIO(cv_bytes)).paragraphs)
        if p.text.strip()
    )
    cv_mod_prompt = (
        "You are a CV editor. Tailor the CV to the job description.\n\n"
        "Return a JSON array of edits. Each edit:\n"
        '  {"index": N, "action": "replace", "text": "rewritten paragraph"}\n'
        '  {"index": N, "action": "remove"}\n\n'
        "GOLDEN RULE: only use words/tools already in the CV. Never invent skills.\n\n"
        f"CV:\n{para_list}\n\nJob Description:\n{job_description}"
    )
    cv_resp = groq_client.chat.completions.create(
        model=_LARGE(),
        messages=[{"role": "user", "content": cv_mod_prompt}],
    )
    raw_mods = re.sub(r"```(?:json)?\s*|\s*```", "", cv_resp.choices[0].message.content.strip())
    modifications = json.loads(raw_mods)
    tailored_cv_bytes = _apply_cv_modifications(cv_bytes, modifications)

    return tailored_cv_bytes, cl_bytes, cl_text
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/tailorer/test_tailor.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/backend/tailorer/tailor.py backend/tests/tailorer/test_tailor.py
git commit -m "feat(tailorer): CV + cover letter generation logic"
```

---

## Task 9: LangGraph state + agent graph definition

**Files:**
- Create: `backend/backend/tailorer/agent.py`

- [ ] **Step 1: Write `agent.py`**

```python
# backend/backend/tailorer/agent.py
import os
import uuid
from typing import TypedDict, Any

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.tailorer.nodes import (
    navigate_to_apply,
    tailor_documents,
    fill_page,
    navigate_next,
    node_done,
)


class TailorerState(TypedDict):
    # Session context (set at start, read-only)
    job_id: str
    user_id: str
    job_title: str
    job_description: str
    company_homepage: str
    profile: dict          # serialized ApplicantProfile fields
    cv_text: str

    # Agent state (mutated during execution)
    apply_url: str
    current_page: int
    filled_fields: dict[str, str]
    cv_bytes: bytes
    cl_bytes: bytes
    cl_text: str
    last_snapshot: dict | None    # cached DOM snapshot, cleared after navigate_next
    pending_correction: str | None  # set when user sends user_correction
    retry_count: int
    status: str  # navigating | tailoring | filling | filling_correction | done | failed


def _route_after_fill(state: TailorerState) -> str:
    if state["status"] in ("filling", "filling_correction"):
        return "fill_page"
    return "navigate_next"


def _route_after_navigate_next(state: TailorerState) -> str:
    if state["status"] == "done":
        return "done"
    return "fill_page"


def build_graph(checkpointer: AsyncPostgresSaver) -> Any:
    graph = StateGraph(TailorerState)

    graph.add_node("navigate_to_apply", navigate_to_apply)
    graph.add_node("tailor_documents", tailor_documents)
    graph.add_node("fill_page", fill_page)
    graph.add_node("navigate_next", navigate_next)
    graph.add_node("done", node_done)

    graph.set_entry_point("navigate_to_apply")
    graph.add_edge("navigate_to_apply", "tailor_documents")
    graph.add_edge("tailor_documents", "fill_page")
    graph.add_conditional_edges("fill_page", _route_after_fill)
    graph.add_conditional_edges("navigate_next", _route_after_navigate_next)
    graph.add_edge("done", END)

    return graph.compile(checkpointer=checkpointer)
```

- [ ] **Step 2: Commit**

```bash
git add backend/backend/tailorer/agent.py
git commit -m "feat(tailorer): LangGraph StateGraph definition"
```

---

## Task 10: LangGraph nodes

**Files:**
- Create: `backend/backend/tailorer/nodes.py`
- Create: `backend/tests/tailorer/test_nodes.py`

- [ ] **Step 1: Write failing tests for node helpers**

```python
# backend/tests/tailorer/test_nodes.py
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_state(**overrides):
    base = {
        "job_id": "abc",
        "user_id": "user1",
        "job_title": "ML Engineer",
        "job_description": "Build ML systems",
        "company_homepage": "https://stripe.com",
        "profile": {"first_name": "Lorenzo", "email": "l@test.com"},
        "cv_text": "Lorenzo Schiroli, ML Engineer",
        "apply_url": "",
        "current_page": 0,
        "filled_fields": {},
        "cv_bytes": b"",
        "cl_bytes": b"",
        "cl_text": "",
        "last_snapshot": None,
        "pending_correction": None,
        "retry_count": 0,
        "status": "navigating",
    }
    return {**base, **overrides}


def test_find_best_link_returns_url():
    from backend.tailorer.nodes import _find_best_link_in_snapshot
    snapshot = {
        "links": [
            {"label": "Careers", "href": "https://stripe.com/jobs"},
            {"label": "About", "href": "https://stripe.com/about"},
        ]
    }
    # Returns the first link that contains keywords related to the goal
    result = _find_best_link_in_snapshot(snapshot, ["careers", "jobs"])
    assert result == "https://stripe.com/jobs"


def test_find_best_link_returns_none_when_no_match():
    from backend.tailorer.nodes import _find_best_link_in_snapshot
    snapshot = {"links": [{"label": "About", "href": "https://stripe.com/about"}]}
    result = _find_best_link_in_snapshot(snapshot, ["careers", "jobs"])
    assert result is None


def test_build_fill_commands_maps_profile_fields():
    import json
    from unittest.mock import patch, MagicMock

    mock_resp = MagicMock()
    mock_resp.content = json.dumps([
        {"field_id": "first_name", "value": "Lorenzo", "uncertain": False}
    ])

    with patch("backend.tailorer.nodes.ChatGroq") as MockLLM:
        instance = MockLLM.return_value
        instance.invoke.return_value = mock_resp
        from backend.tailorer.nodes import _map_fields_sync
        state = _make_state()
        snapshot = {"fields": [{"id": "first_name", "label": "First Name", "type": "text", "value": ""}]}
        cmds = _map_fields_sync(instance, snapshot, state)
    assert cmds[0]["field_id"] == "first_name"
    assert cmds[0]["value"] == "Lorenzo"
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && uv run pytest tests/tailorer/test_nodes.py -v
```

Expected: FAIL — import error.

- [ ] **Step 3: Write `nodes.py`**

```python
# backend/backend/tailorer/nodes.py
import json
import os
import re
import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langgraph.types import interrupt

from backend.tailorer.agent import TailorerState

_BASE = lambda: os.environ["GROQ_MODEL_BASE"]
_LARGE = lambda: os.environ["GROQ_MODEL_LARGE"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_best_link_in_snapshot(snapshot: dict, keywords: list[str]) -> str | None:
    """Fast keyword match over snapshot links. Returns href or None."""
    for link in snapshot.get("links", []):
        label = (link.get("label") or link.get("text") or "").lower()
        href = link.get("href") or ""
        combined = label + " " + href.lower()
        if any(kw in combined for kw in keywords):
            return href
    return None


def _map_fields_sync(llm, snapshot: dict, state: TailorerState) -> list[dict]:
    SYSTEM = (
        "You fill job application form fields from the applicant's profile and CV.\n\n"
        "Return a JSON array of fill commands, each:\n"
        '  {"field_id":"<id>","value":"<value>","uncertain":false}\n\n'
        "For file upload fields (type=file):\n"
        '  {"field_id":"<id>","value":"__CV__","type":"file"}      <- for CV/resume\n'
        '  {"field_id":"<id>","value":"__COVER_LETTER__","type":"file"}  <- for cover letter\n\n'
        "Rules:\n"
        "- uncertain=true if you are not sure of the correct value\n"
        "- Omit fields you have no data for\n"
        "- For dropdowns, use exact text from the options array\n"
        "- Return ONLY the JSON array, no prose\n"
    )
    profile_str = json.dumps(state["profile"], indent=2)
    fields_str = json.dumps(snapshot.get("fields", []), indent=2)
    resp = llm.invoke([
        SystemMessage(content=SYSTEM),
        HumanMessage(content=(
            f"Profile:\n{profile_str}\n\n"
            f"CV (excerpt):\n{state['cv_text'][:3000]}\n\n"
            f"Cover letter:\n{state['cl_text'][:800]}\n\n"
            f"Form fields:\n{fields_str}"
        ))
    ])
    raw = re.sub(r"```(?:json)?\s*|\s*```", "", resp.content.strip())
    return json.loads(raw)


def _apply_correction_sync(llm, correction_text: str, original_commands: list[dict], state: TailorerState) -> list[dict]:
    resp = llm.invoke([
        SystemMessage(content="Correct job application fill commands based on user feedback. Return the corrected JSON array only."),
        HumanMessage(content=(
            f"Original commands:\n{json.dumps(original_commands, indent=2)}\n\n"
            f"User correction: {correction_text}\n\n"
            f"Profile:\n{json.dumps(state['profile'], indent=2)}"
        ))
    ])
    raw = re.sub(r"```(?:json)?\s*|\s*```", "", resp.content.strip())
    return json.loads(raw)


def _find_apply_url_in_snapshot(llm, snapshot: dict, job_title: str) -> str | None:
    """Use LLM to find the apply form URL from a snapshot."""
    links = snapshot.get("links", [])
    if not links:
        return None
    links_str = "\n".join(f"- {l.get('label','')}: {l.get('href','')}" for l in links[:40])
    resp = llm.invoke([
        HumanMessage(content=(
            f"Goal: find the URL for applying to '{job_title}' or a general 'Apply Now' / careers link.\n\n"
            f"Links:\n{links_str}\n\n"
            "Return only the URL, or 'none' if no match."
        ))
    ])
    url = resp.content.strip()
    return None if url.lower() == "none" else url


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def navigate_to_apply(state: TailorerState) -> TailorerState:
    llm = ChatGroq(model=_BASE(), api_key=os.environ["GROQ_API_KEY"])
    retry = state["retry_count"]

    # Navigate to company homepage
    snapshot = interrupt({"type": "navigate", "url": state["company_homepage"]})

    # Find careers page
    careers_url = _find_best_link_in_snapshot(snapshot, ["career", "job", "hiring", "work with us", "vacancies"])
    if not careers_url:
        retry += 1
        if retry >= 2:
            interrupt({"type": "show_stuck", "message": "Can't find the careers page. Can you navigate there for me?"})
            retry = 0
        return {**state, "retry_count": retry}

    # Navigate to careers
    snapshot = interrupt({"type": "navigate", "url": careers_url})

    # Find the specific job
    apply_url = _find_apply_url_in_snapshot(llm, snapshot, state["job_title"])
    if not apply_url:
        retry += 1
        if retry >= 2:
            interrupt({"type": "show_stuck", "message": f"Can't find '{state['job_title']}' on the careers page. Can you click the job for me?"})
            retry = 0
        return {**state, "retry_count": retry}

    # Navigate to job page, look for apply form link
    snapshot = interrupt({"type": "navigate", "url": apply_url})
    form_url = _find_best_link_in_snapshot(snapshot, ["apply", "application"])
    if form_url:
        snapshot = interrupt({"type": "navigate", "url": form_url})
        apply_url = form_url

    return {**state, "apply_url": apply_url, "status": "tailoring", "retry_count": 0}


def tailor_documents(state: TailorerState) -> TailorerState:
    from groq import Groq
    from backend.tailorer.tailor import generate_tailored_documents

    groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])

    if not state["cv_bytes"]:
        # No CV bytes yet — generate blank cv from cv_text as fallback
        import io, docx as _docx
        doc = _docx.Document()
        for line in (state["cv_text"] or "").split("\n"):
            doc.add_paragraph(line)
        buf = io.BytesIO()
        doc.save(buf)
        cv_bytes = buf.getvalue()
    else:
        cv_bytes = state["cv_bytes"]

    tailored_cv, cl_bytes, cl_text = generate_tailored_documents(
        cv_text=state["cv_text"],
        cv_bytes=cv_bytes,
        job_description=state["job_description"],
        groq_client=groq_client,
    )
    return {**state, "cv_bytes": tailored_cv, "cl_bytes": cl_bytes, "cl_text": cl_text, "status": "filling"}


def fill_page(state: TailorerState) -> TailorerState:
    llm = ChatGroq(model=_BASE(), api_key=os.environ["GROQ_API_KEY"])

    # Use cached snapshot if we're in a correction loop; otherwise request fresh one
    if state["last_snapshot"] is None:
        snapshot = interrupt({"type": "request_snapshot"})
        state = {**state, "last_snapshot": snapshot}
    else:
        snapshot = state["last_snapshot"]

    # Build fill commands (applying any pending correction)
    commands = _map_fields_sync(llm, snapshot, state)
    if state["pending_correction"]:
        commands = _apply_correction_sync(llm, state["pending_correction"], commands, state)

    uncertain = [c["field_id"] for c in commands if c.get("uncertain")]
    page_label = f"page {state['current_page'] + 1}"

    response = interrupt({
        "type": "fill_and_confirm",
        "commands": commands,
        "summary": f"Filled {len(commands)} fields on {page_label}",
        "uncertain_fields": uncertain,
    })

    if response["type"] == "user_approved":
        updated_fields = {**state["filled_fields"], **{c["field_id"]: c["value"] for c in commands}}
        return {**state, "filled_fields": updated_fields, "last_snapshot": None, "pending_correction": None, "status": "navigating"}
    elif response["type"] == "user_correction":
        return {**state, "pending_correction": response["text"], "status": "filling_correction"}
    elif response["type"] == "user_manual_edit":
        updated_fields = {**state["filled_fields"], response["field_id"]: response["value"]}
        return {**state, "filled_fields": updated_fields, "pending_correction": None, "status": "filling_correction"}
    return state


def navigate_next(state: TailorerState) -> TailorerState:
    # Ask extension to click next/submit and send back what happened
    response = interrupt({"type": "navigate_next"})

    if response.get("submitted"):
        return {**state, "status": "done"}
    # More pages: increment page count, clear snapshot cache
    return {**state, "current_page": state["current_page"] + 1, "last_snapshot": None, "status": "filling"}


async def node_done(state: TailorerState) -> TailorerState:
    # Record application in DB — done via the WS router after graph completes
    return {**state, "status": "done"}
```

- [ ] **Step 4: Run tests**

```bash
cd backend && uv run pytest tests/tailorer/test_nodes.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/backend/tailorer/nodes.py backend/tests/tailorer/test_nodes.py
git commit -m "feat(tailorer): LangGraph nodes — navigate, tailor, fill, confirm, done"
```

---

## Task 11: WebSocket endpoint + interrupt handler

**Files:**
- Modify: `backend/backend/tailorer/router.py`
- Create: `backend/tests/tailorer/test_ws.py`

- [ ] **Step 1: Write failing WS test**

```python
# backend/tests/tailorer/test_ws.py
import pytest
import uuid
from unittest.mock import patch, AsyncMock, MagicMock
from starlette.testclient import TestClient

from backend.main import app
from backend.auth.jwt import create_access_token


def _make_user_and_token(db_session_sync):
    """Helper — use in sync TestClient WS tests."""
    # This test is intentionally thin: just verifies WS accepts and rejects bad token
    pass


def test_ws_rejects_missing_token(client):
    """WebSocket without token param gets 403."""
    from starlette.testclient import TestClient
    with TestClient(app) as tc:
        import uuid
        job_id = str(uuid.uuid4())
        with pytest.raises(Exception):
            with tc.websocket_connect(f"/tailorer/ws/{job_id}"):
                pass  # should fail at handshake
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && uv run pytest tests/tailorer/test_ws.py -v
```

Expected: FAIL.

- [ ] **Step 3: Add WebSocket endpoint to `router.py`**

Add these imports and functions to `backend/backend/tailorer/router.py`:

```python
import asyncio
import json
import uuid as _uuid

from fastapi import WebSocket, WebSocketDisconnect, Query
from sqlalchemy import select
from langchain_groq import ChatGroq
from langgraph.types import Command

from backend.models import Job, Company
from backend.tailorer.agent import TailorerState, build_graph
from backend.tailorer.models import Application
from backend.auth.jwt import decode_access_token   # or however JWT is verified


async def _get_user_from_token(token: str, session) -> "User":
    from backend.models import User
    from backend.auth.jwt import decode_access_token
    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise ValueError("Invalid token")
    result = await session.execute(select(User).where(User.id == _uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError("User not found")
    return user


async def _handle_interrupt(ws: WebSocket, interrupt_val: dict) -> dict:
    """Route one interrupt payload to the extension and return the response."""
    itype = interrupt_val.get("type")

    if itype == "navigate":
        await ws.send_json({"type": "navigate", "url": interrupt_val["url"]})
        return await ws.receive_json()

    elif itype == "request_snapshot":
        await ws.send_json({"type": "request_snapshot"})
        return await ws.receive_json()

    elif itype == "fill_and_confirm":
        for cmd in interrupt_val.get("commands", []):
            await ws.send_json(cmd)
        await ws.send_json({
            "type": "show_confirm",
            "summary": interrupt_val.get("summary", ""),
            "uncertain_fields": interrupt_val.get("uncertain_fields", []),
        })
        return await ws.receive_json()

    elif itype == "show_confirm":
        await ws.send_json(interrupt_val)
        return await ws.receive_json()

    elif itype == "navigate_next":
        await ws.send_json({"type": "navigate_next"})
        return await ws.receive_json()

    elif itype == "show_stuck":
        await ws.send_json({"type": "show_stuck", "message": interrupt_val["message"]})
        return await ws.receive_json()

    return {"type": "unknown"}


@router.websocket("/ws/{job_id}")
async def tailorer_ws(
    websocket: WebSocket,
    job_id: _uuid.UUID,
    token: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    # Authenticate
    try:
        user = await _get_user_from_token(token, session)
    except Exception:
        await websocket.close(code=4001)
        return

    await websocket.accept()

    # Load job + company + profile
    job_result = await session.execute(
        select(Job).where(Job.id == job_id)
    )
    job = job_result.scalar_one_or_none()
    if not job:
        await websocket.send_json({"type": "error", "message": "Job not found"})
        await websocket.close()
        return

    company_result = await session.execute(
        select(Company).where(Company.id == job.company_id)
    )
    company = company_result.scalar_one_or_none()

    from backend.tailorer.models import ApplicantProfile
    profile_result = await session.execute(
        select(ApplicantProfile).where(ApplicantProfile.user_id == user.id)
    )
    profile = profile_result.scalar_one_or_none()

    if not profile or not profile.cv_text:
        await websocket.send_json({"type": "error", "message": "No CV on file. Upload your CV first."})
        await websocket.close()
        return

    thread_id = str(_uuid.uuid4())
    await websocket.send_json({"type": "session_started", "thread_id": thread_id})

    initial_state = TailorerState(
        job_id=str(job.id),
        user_id=str(user.id),
        job_title=job.title,
        job_description=job.description or "",
        company_homepage=company.website if company else "",
        profile={
            "first_name": profile.first_name,
            "last_name": profile.last_name,
            "email": profile.email,
            "phone": profile.phone,
            "city": profile.city,
            "country": profile.country,
            "work_auth": profile.work_auth,
            "urls": profile.urls or {},
            "extra_qa": profile.extra_qa or {},
        },
        cv_text=profile.cv_text or "",
        apply_url="",
        current_page=0,
        filled_fields={},
        cv_bytes=b"",
        cl_bytes=b"",
        cl_text="",
        last_snapshot=None,
        pending_correction=None,
        retry_count=0,
        status="navigating",
    )

    config = {"configurable": {"thread_id": thread_id}}

    # Build checkpointer (retrieved from app state set at startup)
    from backend.main import get_checkpointer
    checkpointer = get_checkpointer()
    graph = build_graph(checkpointer)

    try:
        current_input = initial_state
        while True:
            # Run graph until next interrupt or completion
            await graph.ainvoke(current_input, config)

            state_snapshot = await graph.aget_state(config)
            if not state_snapshot.next:
                # Graph completed
                await websocket.send_json({"type": "done", "message": "Application submitted!"})
                # Record in DB
                app_record = Application(user_id=user.id, job_id=job_id)
                session.add(app_record)
                await session.commit()
                break

            # Get interrupt
            interrupts = [i for task in state_snapshot.tasks for i in task.interrupts]
            if not interrupts:
                break

            resume_val = await _handle_interrupt(websocket, interrupts[0].value)
            current_input = Command(resume=resume_val)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        await websocket.close()
```

- [ ] **Step 4: Run tests**

```bash
cd backend && uv run pytest tests/tailorer/test_ws.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/backend/tailorer/router.py backend/tests/tailorer/test_ws.py
git commit -m "feat(tailorer): WebSocket endpoint with interrupt-driven agent loop"
```

---

## Task 12: File download endpoint

**Files:**
- Modify: `backend/backend/tailorer/router.py`

The tailored CV and cover letter bytes live in LangGraph state (persisted by `AsyncPostgresSaver`). The download endpoint reads them from the checkpointer.

- [ ] **Step 1: Add file download endpoint to `router.py`**

```python
@router.get("/files/{thread_id}/{file_type}")
async def download_tailored_file(
    thread_id: str,
    file_type: str,  # "cv" or "cover_letter"
    token: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    from fastapi.responses import Response
    try:
        user = await _get_user_from_token(token, session)
    except Exception:
        raise HTTPException(status_code=403, detail="Invalid token")

    if file_type not in ("cv", "cover_letter"):
        raise HTTPException(status_code=400, detail="file_type must be 'cv' or 'cover_letter'")

    from backend.main import get_checkpointer
    checkpointer = get_checkpointer()
    config = {"configurable": {"thread_id": thread_id}}
    graph = build_graph(checkpointer)
    state_snapshot = await graph.aget_state(config)
    if not state_snapshot or not state_snapshot.values:
        raise HTTPException(status_code=404, detail="Session not found")

    values = state_snapshot.values
    # Verify this session belongs to the requesting user
    if values.get("user_id") != str(user.id):
        raise HTTPException(status_code=403, detail="Forbidden")

    key = "cv_bytes" if file_type == "cv" else "cl_bytes"
    file_bytes = values.get(key, b"")
    if not file_bytes:
        raise HTTPException(status_code=404, detail="File not yet generated")

    filename = "tailored_cv.docx" if file_type == "cv" else "cover_letter.docx"
    return Response(
        content=file_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

- [ ] **Step 2: Commit**

```bash
git add backend/backend/tailorer/router.py
git commit -m "feat(tailorer): file download endpoint for tailored CV and cover letter"
```

---

## Task 13: Wire up main.py — register router + checkpointer setup

**Files:**
- Modify: `backend/backend/main.py`

- [ ] **Step 1: Update `main.py`**

Add a module-level checkpointer variable and update the lifespan:

```python
# At top of backend/backend/main.py, add:
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

_checkpointer: AsyncPostgresSaver | None = None


def get_checkpointer() -> AsyncPostgresSaver:
    if _checkpointer is None:
        raise RuntimeError("Checkpointer not initialized")
    return _checkpointer
```

Update the lifespan context manager — add checkpointer setup before the outbox worker:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _checkpointer
    init_models()
    await init_opensearch()
    await _backfill_created_at()

    # Set up LangGraph checkpointer (creates its own tables if not present)
    db_url = os.environ["DATABASE_URL"].replace("+asyncpg", "")  # psycopg needs plain postgres://
    async with await AsyncPostgresSaver.from_conn_string(db_url) as checkpointer:
        await checkpointer.setup()
        _checkpointer = checkpointer

        task = asyncio.create_task(outbox_worker())
        yield
        task.cancel()
```

Also add the router import and registration (if not already done in Task 7):
```python
from backend.tailorer.router import router as tailorer_router
# in app setup:
app.include_router(tailorer_router)
```

- [ ] **Step 2: Add `DATABASE_URL` to env — it must use `postgresql://` scheme for psycopg**

In `backend/backend/main.py` the `DATABASE_URL` env var currently uses `postgresql+asyncpg://...`. The psycopg checkpointer needs `postgresql://...`. Add:
```python
import os
# In get_checkpointer or lifespan:
db_url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
```

- [ ] **Step 3: Start the dev server to verify it boots**

```bash
cd backend && uv run uvicorn backend.main:app --reload
```

Expected: server starts, logs show `INFO:backend.main:...` with no errors. Hit `GET /health` → `{"status": "ok"}`.

- [ ] **Step 4: Run full test suite**

```bash
cd backend && uv run pytest -v
```

Expected: all existing tests pass, new tailorer tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/backend/main.py
git commit -m "feat(tailorer): wire up tailorer router and AsyncPostgresSaver in lifespan"
```

---

## Task 14: Frontend — write localStorage before opening job link

**Files:**
- Modify: `frontend/src/components/JobCard.tsx`

The extension needs to know the `job_id` when a job link is opened from the frontend. The frontend writes this to `localStorage` before `window.open()`. The extension reads it from the opener tab.

- [ ] **Step 1: Update `JobCard.tsx`**

Replace the entire file:

```tsx
// frontend/src/components/JobCard.tsx
import { Job } from '../api/search'

export default function JobCard({ job }: { job: Job }) {
  const tags = [
    job.employment_type,
    job.location_type,
    job.seniority,
    ...job.languages_required,
  ].filter(Boolean) as string[]

  const handleClick = (e: React.MouseEvent<HTMLAnchorElement>) => {
    // Signal to extension which job is being opened
    try {
      localStorage.setItem('tailorer_pending', JSON.stringify({ job_id: job.id }))
    } catch {
      // localStorage unavailable — extension will fall back to URL-based detection
    }
  }

  return (
    <a
      href={job.url}
      target="_blank"
      rel="noopener noreferrer"
      onClick={handleClick}
      style={{
        display: 'block',
        padding: '1rem',
        border: '1px solid #2a2a2a',
        borderRadius: 8,
        textDecoration: 'none',
        color: 'inherit',
        background: '#141414',
      }}
    >
      <div style={{ fontWeight: 600 }}>{job.title} — {job.company.name}</div>
      <div style={{ fontSize: '0.875rem', opacity: 0.5, marginTop: '0.2rem' }}>
        {[job.location, job.company.country].filter(Boolean).join(' · ')}
      </div>
      {tags.length > 0 && (
        <div style={{ marginTop: '0.5rem', display: 'flex', flexWrap: 'wrap', gap: '0.3rem' }}>
          {tags.map(tag => (
            <span key={tag} style={{ fontSize: '0.75rem', background: '#2a2a2a', padding: '0.15rem 0.5rem', borderRadius: 4 }}>
              {tag}
            </span>
          ))}
        </div>
      )}
    </a>
  )
}
```

- [ ] **Step 2: Verify frontend builds**

```bash
cd frontend && npm run build
```

Expected: no TypeScript errors, build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/JobCard.tsx
git commit -m "feat(tailorer): write tailorer_pending to localStorage on job link click"
```

---

## Self-Review Notes

**Spec coverage check:**
- ✅ applicant_profile table (Task 2, 4)
- ✅ applications junction table (Task 3, 4)
- ✅ users.cv_text migration (Task 2)
- ✅ cv router updated (Task 5)
- ✅ search router updated (Task 5)
- ✅ Profile GET/PUT endpoints (Task 7)
- ✅ Tailor logic — CV + CL generation (Task 8)
- ✅ LangGraph state + graph (Task 9)
- ✅ navigate_to_apply node (Task 10)
- ✅ tailor_documents node (Task 10)
- ✅ fill_page node with correction loop (Task 10)
- ✅ navigate_next + done nodes (Task 10)
- ✅ WebSocket endpoint with interrupt loop (Task 11)
- ✅ File download endpoint (Task 12)
- ✅ AsyncPostgresSaver setup at startup (Task 13)
- ✅ Frontend localStorage write (Task 14)
- ✅ langgraph deps (Task 1)

**Not in this plan (covered in Plan 2 — Extension):**
- extension/ package (manifest, service_worker, dom_inspector, form_filler, overlay)
- externally_connectable handshake
- Service worker reading localStorage from opener tab
