# Advanced Search Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Advanced search mode (LangGraph: clarify → search → one auto-refine → per-result fit scoring) alongside the existing Basic search, plus an editable per-user preference memory and a left sidebar to toggle modes.

**Architecture:** A new `backend/backend/search/advanced/` package holds a LangGraph `StateGraph` whose nodes reuse the existing `extract_filters` / `hybrid_retrieve` / `rerank` helpers and call the LLM via the existing `large_llm()` (langchain-openai → Groq). The graph pauses at a `clarify` interrupt; a two-call HTTP round-trip (`POST /jobs/search/advanced` then `POST /jobs/search/advanced/resume`) drives it using the **already-wired** `AsyncPostgresSaver` checkpointer (`backend.main.get_checkpointer`). A `preference_memory` table + service stores an LLM-distilled, user-editable preference blob fed into clarify + fit scoring. The React frontend gains a persistent left sidebar (mode toggle, identity, nav, editable memory) and an advanced clarify→results flow.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, LangGraph (`langgraph`, `langgraph-checkpoint-postgres`, `langchain-openai` — all already in `backend/pyproject.toml`), OpenSearch, React + Vite + TypeScript, axios.

## Global Constraints

- Python tests require a live Postgres at `postgresql+asyncpg://postgres:postgres@localhost:5432/jobstrainer_test` (override `TEST_DATABASE_URL`). OpenSearch, Groq, and ML models are mocked.
- Run backend tests with `uv run pytest` from `backend/`.
- LLM access goes through `large_llm()` from `backend/backend/tailorer/llm.py` (langchain-openai `ChatOpenAI` pointed at Groq); call with `await llm.ainvoke([SystemMessage(...), HumanMessage(...)])` and read `.content`. Filter extraction reuses the existing Groq-SDK `extract_filters`.
- Do NOT put non-serializable objects (SentenceTransformer, CrossEncoder, AsyncOpenSearch, Groq client, pydantic models) into LangGraph state — the Postgres checkpointer serializes state. Pass those into the graph via `build_graph(...)` closures; keep state to JSON-friendly types (str/list/dict/bool).
- The existing `POST /jobs/search` (Basic) endpoint and its tests must remain unchanged.
- No "Co-Authored-By" trailers in commits.
- Frontend has no test runner; verify frontend tasks with `npm run build` (runs `tsc` then `vite build`) from `frontend/`.
- New Alembic migration: revision `"009"`, `down_revision = "008"`.

---

### Task 1: PreferenceMemory model + migration

**Files:**
- Create: `backend/backend/search/advanced/__init__.py`
- Create: `backend/backend/search/advanced/models.py`
- Create: `backend/alembic/versions/009_add_preference_memory.py`
- Modify: `backend/tests/conftest.py` (register model import so `create_all` builds the table)
- Test: `backend/tests/search/test_preference_memory_model.py`

**Interfaces:**
- Produces: `PreferenceMemory` ORM model with columns `id`, `user_id` (unique FK), `memory_text: str | None`, `user_edited: bool`, `created_at`, `updated_at`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/search/test_preference_memory_model.py
import uuid
import pytest
from sqlalchemy import select
from backend.models import User
from backend.search.advanced.models import PreferenceMemory

pytestmark = pytest.mark.asyncio


async def test_preference_memory_round_trip(db_session):
    user = User(id=uuid.uuid4(), username="pmuser", password_hash="x")
    db_session.add(user)
    await db_session.flush()

    pm = PreferenceMemory(user_id=user.id, memory_text="prefers startups", user_edited=True)
    db_session.add(pm)
    await db_session.commit()

    row = (await db_session.execute(
        select(PreferenceMemory).where(PreferenceMemory.user_id == user.id)
    )).scalar_one()
    assert row.memory_text == "prefers startups"
    assert row.user_edited is True


async def test_user_edited_defaults_false(db_session):
    user = User(id=uuid.uuid4(), username="pmuser2", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    pm = PreferenceMemory(user_id=user.id, memory_text="x")
    db_session.add(pm)
    await db_session.commit()
    await db_session.refresh(pm)
    assert pm.user_edited is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/search/test_preference_memory_model.py -v`
Expected: FAIL with `ModuleNotFoundError: backend.search.advanced.models`

- [ ] **Step 3: Create the package and model**

```python
# backend/backend/search/advanced/__init__.py
```
(empty file)

```python
# backend/backend/search/advanced/models.py
import uuid
from datetime import datetime
from sqlalchemy import Boolean, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.models import Base


class PreferenceMemory(Base):
    __tablename__ = "preference_memory"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    memory_text: Mapped[str | None] = mapped_column(Text)
    user_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
```

- [ ] **Step 4: Register the model import in conftest**

In `backend/tests/conftest.py`, find the line:
```python
import backend.tailorer.models  # noqa: F401
```
Add directly below it:
```python
import backend.search.advanced.models  # noqa: F401
```

- [ ] **Step 5: Write the Alembic migration**

```python
# backend/alembic/versions/009_add_preference_memory.py
"""add preference_memory table

Revision ID: 009
Revises: 008
Create Date: 2026-06-28
"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "preference_memory",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_text", sa.Text(), nullable=True),
        sa.Column("user_edited", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_preference_memory_user"),
    )


def downgrade() -> None:
    op.drop_table("preference_memory")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/search/test_preference_memory_model.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Commit**

```bash
git add backend/backend/search/advanced/__init__.py backend/backend/search/advanced/models.py backend/alembic/versions/009_add_preference_memory.py backend/tests/conftest.py backend/tests/search/test_preference_memory_model.py
git commit -m "feat(search): add preference_memory model and migration"
```

---

### Task 2: Preference memory service — get/set

**Files:**
- Create: `backend/backend/search/advanced/preference_memory.py`
- Test: `backend/tests/search/test_preference_memory_service.py`

**Interfaces:**
- Consumes: `PreferenceMemory` (Task 1).
- Produces:
  - `async def get_memory(session: AsyncSession, user_id: uuid.UUID) -> PreferenceMemory | None`
  - `async def set_memory(session: AsyncSession, user_id: uuid.UUID, text: str) -> PreferenceMemory` — upserts, sets `user_edited=True`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/search/test_preference_memory_service.py
import uuid
import pytest
from backend.models import User
from backend.search.advanced import preference_memory as svc

pytestmark = pytest.mark.asyncio


async def _make_user(db_session):
    user = User(id=uuid.uuid4(), username=f"u{uuid.uuid4().hex[:8]}", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    return user


async def test_get_memory_none_when_absent(db_session):
    user = await _make_user(db_session)
    assert await svc.get_memory(db_session, user.id) is None


async def test_set_memory_creates_and_marks_edited(db_session):
    user = await _make_user(db_session)
    pm = await svc.set_memory(db_session, user.id, "prefers remote, avoids consulting")
    assert pm.memory_text == "prefers remote, avoids consulting"
    assert pm.user_edited is True


async def test_set_memory_updates_existing(db_session):
    user = await _make_user(db_session)
    await svc.set_memory(db_session, user.id, "first")
    pm = await svc.set_memory(db_session, user.id, "second")
    assert pm.memory_text == "second"
    got = await svc.get_memory(db_session, user.id)
    assert got.memory_text == "second"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/search/test_preference_memory_service.py -v`
Expected: FAIL with `ImportError` / `AttributeError: get_memory`

- [ ] **Step 3: Write the service (get/set only)**

```python
# backend/backend/search/advanced/preference_memory.py
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.search.advanced.models import PreferenceMemory


async def get_memory(session: AsyncSession, user_id: uuid.UUID) -> PreferenceMemory | None:
    result = await session.execute(
        select(PreferenceMemory).where(PreferenceMemory.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def set_memory(session: AsyncSession, user_id: uuid.UUID, text: str) -> PreferenceMemory:
    pm = await get_memory(session, user_id)
    if pm is None:
        pm = PreferenceMemory(user_id=user_id)
        session.add(pm)
    pm.memory_text = text
    pm.user_edited = True
    await session.commit()
    await session.refresh(pm)
    return pm
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/search/test_preference_memory_service.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/backend/search/advanced/preference_memory.py backend/tests/search/test_preference_memory_service.py
git commit -m "feat(search): preference memory get/set service"
```

---

### Task 3: Preference memory endpoints (`GET`/`PUT /me/preference-memory`)

**Files:**
- Create: `backend/backend/routers/preferences.py`
- Modify: `backend/backend/main.py` (register router)
- Test: `backend/tests/search/test_preferences_endpoint.py`

**Interfaces:**
- Consumes: `get_memory`, `set_memory` (Task 2); `get_current_user`, `get_session`.
- Produces: `GET /me/preference-memory` → `{memory_text: str|None, user_edited: bool}`; `PUT /me/preference-memory` body `{memory_text: str}` → same shape with `user_edited: true`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/search/test_preferences_endpoint.py
import uuid
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.main import app
from backend.database import get_session
from backend.auth.dependencies import get_current_user
from backend.models import User

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def prefs_client(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(User(id=user_id, username="prefuser", password_hash="x"))
        await session.commit()
    mock_user = User(id=user_id, username="prefuser", password_hash="x")

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = lambda: mock_user

    with patch("backend.main.init_models"), \
         patch("backend.main.init_opensearch", new_callable=AsyncMock), \
         patch("backend.main.outbox_worker", new_callable=AsyncMock), \
         patch("backend.main._backfill_created_at", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.clear()


async def test_get_returns_null_when_absent(prefs_client):
    resp = await prefs_client.get("/me/preference-memory")
    assert resp.status_code == 200
    assert resp.json() == {"memory_text": None, "user_edited": False}


async def test_put_then_get_round_trip(prefs_client):
    put = await prefs_client.put("/me/preference-memory", json={"memory_text": "prefers remote"})
    assert put.status_code == 200
    assert put.json() == {"memory_text": "prefers remote", "user_edited": True}

    get = await prefs_client.get("/me/preference-memory")
    assert get.json()["memory_text"] == "prefers remote"
    assert get.json()["user_edited"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/search/test_preferences_endpoint.py -v`
Expected: FAIL with 404 (route not registered)

- [ ] **Step 3: Write the router**

```python
# backend/backend/routers/preferences.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models import User
from backend.auth.dependencies import get_current_user
from backend.search.advanced.preference_memory import get_memory, set_memory

router = APIRouter(prefix="/me", tags=["preferences"])


class PreferenceMemoryResponse(BaseModel):
    memory_text: str | None
    user_edited: bool


class PreferenceMemoryUpdate(BaseModel):
    memory_text: str


@router.get("/preference-memory", response_model=PreferenceMemoryResponse)
async def read_preference_memory(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PreferenceMemoryResponse:
    pm = await get_memory(session, current_user.id)
    if pm is None:
        return PreferenceMemoryResponse(memory_text=None, user_edited=False)
    return PreferenceMemoryResponse(memory_text=pm.memory_text, user_edited=pm.user_edited)


@router.put("/preference-memory", response_model=PreferenceMemoryResponse)
async def write_preference_memory(
    body: PreferenceMemoryUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PreferenceMemoryResponse:
    pm = await set_memory(session, current_user.id, body.memory_text)
    return PreferenceMemoryResponse(memory_text=pm.memory_text, user_edited=pm.user_edited)
```

- [ ] **Step 4: Register the router in main.py**

In `backend/backend/main.py`, add to the import block near the other routers:
```python
from backend.routers.preferences import router as preferences_router
```
And after `app.include_router(tailorer_router)` add:
```python
app.include_router(preferences_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/search/test_preferences_endpoint.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/backend/routers/preferences.py backend/backend/main.py backend/tests/search/test_preferences_endpoint.py
git commit -m "feat(search): preference memory GET/PUT endpoints"
```

---

### Task 4: Advanced LLM helpers (clarify, critique, fit-score, distill)

**Files:**
- Create: `backend/backend/search/advanced/llm.py`
- Modify: `backend/backend/search/advanced/preference_memory.py` (add `update_memory_from_session`)
- Test: `backend/tests/search/test_advanced_llm.py`

**Interfaces:**
- Consumes: `large_llm` from `backend.tailorer.llm`.
- Produces (all in `advanced/llm.py`):
  - `async def generate_clarify_questions(query: str, cv_text: str, preference_memory: str) -> list[str]`
  - `async def critique_results(query: str, hits: list[dict]) -> dict` → `{"need_refine": bool, "refined_query": str | None}`
  - `async def score_fit(cv_text: str, preference_memory: str, hits: list[dict]) -> list[dict]` → list of `{"job_id": str, "fit_score": int, "fit_rationale": str, "fit_gaps": str}`
  - `async def distill_memory(existing: str, user_edited: bool, query: str, filters_summary: str, clarify_qa: list[tuple[str, str]]) -> str`
- In `preference_memory.py`: `async def update_memory_from_session(session, user_id, query, filters_summary, clarify_qa) -> PreferenceMemory` (calls `distill_memory`, never sets `user_edited`).

Each helper sends `[SystemMessage, HumanMessage]` to `large_llm()` and parses a JSON response (strip ```` ```json ```` fences like `tailorer/form.py` does).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/search/test_advanced_llm.py
import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.models import User

pytestmark = pytest.mark.asyncio


def _mock_llm(content: str):
    resp = MagicMock()
    resp.content = content
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=resp)
    return llm


async def test_generate_clarify_questions_parses_list():
    from backend.search.advanced import llm
    with patch.object(llm, "large_llm", return_value=_mock_llm('["Remote only?", "Which countries?"]')):
        qs = await llm.generate_clarify_questions("ml engineer", "cv", "")
    assert qs == ["Remote only?", "Which countries?"]


async def test_critique_results_parses_dict():
    from backend.search.advanced import llm
    payload = json.dumps({"need_refine": True, "refined_query": "senior ml engineer pytorch"})
    with patch.object(llm, "large_llm", return_value=_mock_llm(payload)):
        out = await llm.critique_results("ml", [{"_source": {"summary_text": "x"}}])
    assert out == {"need_refine": True, "refined_query": "senior ml engineer pytorch"}


async def test_score_fit_parses_scored_list():
    from backend.search.advanced import llm
    payload = json.dumps([
        {"job_id": "j1", "fit_score": 82, "fit_rationale": "strong overlap", "fit_gaps": "no kubernetes"}
    ])
    hits = [{"_source": {"job_id": "j1", "summary_text": "ml role"}}]
    with patch.object(llm, "large_llm", return_value=_mock_llm(payload)):
        out = await llm.score_fit("cv", "", hits)
    assert out[0]["job_id"] == "j1"
    assert out[0]["fit_score"] == 82
    assert out[0]["fit_gaps"] == "no kubernetes"


async def test_distill_memory_returns_text():
    from backend.search.advanced import llm
    with patch.object(llm, "large_llm", return_value=_mock_llm("prefers remote ml roles in EU")):
        out = await llm.distill_memory("", False, "ml engineer", "remote=true", [("Remote?", "yes")])
    assert "remote" in out.lower()


async def test_update_memory_from_session_persists_distilled(db_session):
    from backend.search.advanced import preference_memory as svc
    user = User(id=uuid.uuid4(), username=f"u{uuid.uuid4().hex[:6]}", password_hash="x")
    db_session.add(user)
    await db_session.flush()

    with patch("backend.search.advanced.preference_memory.distill_memory",
               new=AsyncMock(return_value="distilled blob")):
        pm = await svc.update_memory_from_session(db_session, user.id, "ml engineer", "remote=true", [("Remote?", "yes")])
    assert pm.memory_text == "distilled blob"
    assert pm.user_edited is False


async def test_update_memory_preserves_user_edited_flag(db_session):
    from backend.search.advanced import preference_memory as svc
    user = User(id=uuid.uuid4(), username=f"u{uuid.uuid4().hex[:6]}", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    await svc.set_memory(db_session, user.id, "user wrote this")  # user_edited=True

    captured = {}
    async def fake_distill(existing, user_edited, *a, **k):
        captured["existing"] = existing
        captured["user_edited"] = user_edited
        return existing + " + appended"
    with patch("backend.search.advanced.preference_memory.distill_memory", new=fake_distill):
        pm = await svc.update_memory_from_session(db_session, user.id, "q", "f", [])
    assert captured["user_edited"] is True
    assert captured["existing"] == "user wrote this"
    assert pm.user_edited is True  # stays True after distill
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/search/test_advanced_llm.py -v`
Expected: FAIL with `ModuleNotFoundError: backend.search.advanced.llm`

- [ ] **Step 3: Write `advanced/llm.py`**

```python
# backend/backend/search/advanced/llm.py
import json
import re
import logging
from langchain_core.messages import HumanMessage, SystemMessage

from backend.tailorer.llm import large_llm

_log = logging.getLogger(__name__)


def _parse_json(raw: str):
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw.strip())
    return json.loads(cleaned)


_CLARIFY_SYSTEM = (
    "You help refine a job search. Given a user's query, their CV, and known preferences, "
    "produce AT MOST 2 short clarifying questions that would most improve the search. "
    "If the query is already clear, return fewer or an empty list. "
    "Return ONLY a JSON array of question strings, no prose, no markdown fences."
)

_CRITIQUE_SYSTEM = (
    "You judge whether a set of retrieved job results matches the user's intent. "
    "If the results look weak or off-target, propose ONE improved semantic search query. "
    'Return ONLY a JSON object: {"need_refine": boolean, "refined_query": string or null}. '
    "Set need_refine=false and refined_query=null when results are already good."
)

_FIT_SYSTEM = (
    "You evaluate how well each job fits the applicant, using their CV and preferences. "
    "For each job return a fit_score 0-100, a one-sentence fit_rationale, and a short fit_gaps "
    "note (skills/requirements the applicant would need to address; empty string if none). "
    'Return ONLY a JSON array of objects: '
    '{"job_id": string, "fit_score": integer, "fit_rationale": string, "fit_gaps": string}.'
)

_DISTILL_SYSTEM = (
    "You maintain a short natural-language summary of a job seeker's preferences, learned from "
    "their searches. Merge the new session signals into the existing summary and return the "
    "updated summary (a few sentences). If the existing summary was written by the user "
    "(user_edited=true), preserve their statements verbatim and only APPEND newly observed "
    "signals. Return ONLY the summary text, no prose wrapper, no markdown."
)


async def generate_clarify_questions(query: str, cv_text: str, preference_memory: str) -> list[str]:
    llm = large_llm()
    resp = await llm.ainvoke([
        SystemMessage(content=_CLARIFY_SYSTEM),
        HumanMessage(content=(
            f"Query:\n{query}\n\nCV (excerpt):\n{cv_text[:1500]}\n\n"
            f"Known preferences:\n{preference_memory or '(none)'}"
        )),
    ])
    try:
        data = _parse_json(resp.content)
        return [str(q) for q in data][:2] if isinstance(data, list) else []
    except Exception:
        _log.warning("[advanced.llm] clarify parse failed")
        return []


async def critique_results(query: str, hits: list[dict]) -> dict:
    llm = large_llm()
    titles = "\n".join(f"- {h['_source'].get('summary_text', '')[:200]}" for h in hits[:10])
    resp = await llm.ainvoke([
        SystemMessage(content=_CRITIQUE_SYSTEM),
        HumanMessage(content=f"Query:\n{query}\n\nTop results:\n{titles or '(none)'}"),
    ])
    try:
        data = _parse_json(resp.content)
        return {"need_refine": bool(data.get("need_refine")), "refined_query": data.get("refined_query")}
    except Exception:
        _log.warning("[advanced.llm] critique parse failed")
        return {"need_refine": False, "refined_query": None}


async def score_fit(cv_text: str, preference_memory: str, hits: list[dict]) -> list[dict]:
    llm = large_llm()
    jobs_blob = "\n".join(
        f'{{"job_id": "{h["_source"].get("job_id")}", "summary": "{h["_source"].get("summary_text", "")[:400]}"}}'
        for h in hits
    )
    resp = await llm.ainvoke([
        SystemMessage(content=_FIT_SYSTEM),
        HumanMessage(content=(
            f"CV (excerpt):\n{cv_text[:1500]}\n\nPreferences:\n{preference_memory or '(none)'}\n\n"
            f"Jobs:\n{jobs_blob}"
        )),
    ])
    try:
        data = _parse_json(resp.content)
        return data if isinstance(data, list) else []
    except Exception:
        _log.warning("[advanced.llm] fit-score parse failed")
        return []


async def distill_memory(existing: str, user_edited: bool, query: str, filters_summary: str,
                         clarify_qa: list[tuple[str, str]]) -> str:
    llm = large_llm()
    qa = "\n".join(f"Q: {q} A: {a}" for q, a in clarify_qa) or "(none)"
    resp = await llm.ainvoke([
        SystemMessage(content=_DISTILL_SYSTEM),
        HumanMessage(content=(
            f"Existing summary (user_edited={str(user_edited).lower()}):\n{existing or '(none)'}\n\n"
            f"New session — query: {query}\nfilters: {filters_summary}\nclarifications:\n{qa}"
        )),
    ])
    return resp.content.strip()
```

- [ ] **Step 4: Add `update_memory_from_session` to `preference_memory.py`**

At the top of `backend/backend/search/advanced/preference_memory.py` add the import:
```python
from backend.search.advanced.llm import distill_memory
```
Then append:
```python
async def update_memory_from_session(
    session: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    filters_summary: str,
    clarify_qa: list[tuple[str, str]],
) -> PreferenceMemory:
    pm = await get_memory(session, user_id)
    existing = pm.memory_text if pm else ""
    user_edited = pm.user_edited if pm else False
    new_text = await distill_memory(existing or "", user_edited, query, filters_summary, clarify_qa)
    if pm is None:
        pm = PreferenceMemory(user_id=user_id)
        session.add(pm)
    pm.memory_text = new_text
    # distill never flips user_edited; preserve whatever the user set
    await session.commit()
    await session.refresh(pm)
    return pm
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/search/test_advanced_llm.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/backend/search/advanced/llm.py backend/backend/search/advanced/preference_memory.py backend/tests/search/test_advanced_llm.py
git commit -m "feat(search): advanced LLM helpers + memory distill"
```

---

### Task 5: Advanced graph — state, nodes, build_graph

**Files:**
- Create: `backend/backend/search/advanced/state.py`
- Create: `backend/backend/search/advanced/nodes.py`
- Create: `backend/backend/search/advanced/agent.py`
- Test: `backend/tests/search/test_advanced_nodes.py`

**Interfaces:**
- Consumes: `extract_filters`, `get_groq_client` (`search/query_understanding.py`), `hybrid_retrieve` (`search/retrieval.py`), `rerank` (`search/reranker.py`), advanced llm helpers (Task 4).
- Produces:
  - `AdvancedSearchState` TypedDict: `query, cv_text, preference_memory, clarify_questions, clarify_answers, hits, refined_query, refined_once, need_refine, results`.
  - `async def node_clarify(state) -> dict`
  - `async def node_search(state, *, biencoder, reranker, os_client, groq_client) -> dict`
  - `async def node_critique(state) -> dict`
  - `async def node_fit_score(state) -> dict`
  - `def _route_after_critique(state) -> str` → `"search"` or `"fit_score"`
  - `def build_graph(checkpointer, *, biencoder, reranker, os_client, groq_client)` → compiled graph.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/search/test_advanced_nodes.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

pytestmark = pytest.mark.asyncio


def _hit(job_id, summary):
    return {"_source": {"job_id": job_id, "summary_text": summary}}


async def test_node_search_retrieves_and_reranks():
    from backend.search.advanced import nodes
    biencoder = MagicMock()
    enc = MagicMock(); enc.tolist.return_value = [0.0] * 384
    biencoder.encode.return_value = enc
    reranker = MagicMock()
    os_client = AsyncMock()
    groq_client = MagicMock()

    state = {"query": "ml engineer", "cv_text": "cv", "preference_memory": "",
             "clarify_answers": ["yes"], "refined_query": None, "refined_once": False}

    fake_filters = MagicMock(); fake_filters.semantic_query = "ml engineer"
    with patch("backend.search.advanced.nodes.extract_filters", new=AsyncMock(return_value=fake_filters)), \
         patch("backend.search.advanced.nodes.hybrid_retrieve", new=AsyncMock(return_value=[_hit("j1", "a")])), \
         patch("backend.search.advanced.nodes.rerank", return_value=[_hit("j1", "a")]):
        out = await nodes.node_search(state, biencoder=biencoder, reranker=reranker,
                                      os_client=os_client, groq_client=groq_client)
    assert out["hits"][0]["_source"]["job_id"] == "j1"


async def test_node_search_uses_refined_query_when_present():
    from backend.search.advanced import nodes
    biencoder = MagicMock()
    enc = MagicMock(); enc.tolist.return_value = [0.0] * 384
    biencoder.encode.return_value = enc
    state = {"query": "ml", "cv_text": "cv", "preference_memory": "",
             "clarify_answers": [], "refined_query": "senior ml pytorch", "refined_once": True}
    captured = {}
    async def fake_extract(client, cv, q):
        captured["q"] = q
        f = MagicMock(); f.semantic_query = q; return f
    with patch("backend.search.advanced.nodes.extract_filters", new=fake_extract), \
         patch("backend.search.advanced.nodes.hybrid_retrieve", new=AsyncMock(return_value=[])), \
         patch("backend.search.advanced.nodes.rerank", return_value=[]):
        await nodes.node_search(state, biencoder=biencoder, reranker=MagicMock(),
                                os_client=AsyncMock(), groq_client=MagicMock())
    assert "senior ml pytorch" in captured["q"]


async def test_node_critique_sets_refined_once_guard():
    from backend.search.advanced import nodes
    state = {"query": "ml", "hits": [], "refined_once": False}
    with patch("backend.search.advanced.nodes.critique_results",
               new=AsyncMock(return_value={"need_refine": True, "refined_query": "better"})):
        out = await nodes.node_critique(state)
    assert out["need_refine"] is True
    assert out["refined_once"] is True
    assert out["refined_query"] == "better"


async def test_node_critique_no_refine_when_already_refined():
    from backend.search.advanced import nodes
    state = {"query": "ml", "hits": [], "refined_once": True}
    with patch("backend.search.advanced.nodes.critique_results",
               new=AsyncMock(return_value={"need_refine": True, "refined_query": "better"})):
        out = await nodes.node_critique(state)
    assert out["need_refine"] is False


def test_route_after_critique():
    from backend.search.advanced import nodes
    assert nodes._route_after_critique({"need_refine": True}) == "search"
    assert nodes._route_after_critique({"need_refine": False}) == "fit_score"


async def test_node_fit_score_sorts_by_score():
    from backend.search.advanced import nodes
    state = {"cv_text": "cv", "preference_memory": "",
             "hits": [_hit("j1", "a"), _hit("j2", "b")]}
    scored = [
        {"job_id": "j1", "fit_score": 40, "fit_rationale": "ok", "fit_gaps": ""},
        {"job_id": "j2", "fit_score": 90, "fit_rationale": "great", "fit_gaps": ""},
    ]
    with patch("backend.search.advanced.nodes.score_fit", new=AsyncMock(return_value=scored)):
        out = await nodes.node_fit_score(state)
    assert [r["job_id"] for r in out["results"]] == ["j2", "j1"]


def test_build_graph_compiles():
    from backend.search.advanced.agent import build_graph
    from langgraph.checkpoint.memory import MemorySaver
    graph = build_graph(MemorySaver(), biencoder=MagicMock(), reranker=MagicMock(),
                        os_client=AsyncMock(), groq_client=MagicMock())
    assert graph is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/search/test_advanced_nodes.py -v`
Expected: FAIL with `ModuleNotFoundError: backend.search.advanced.nodes`

- [ ] **Step 3: Write `state.py`**

```python
# backend/backend/search/advanced/state.py
from typing import TypedDict


class AdvancedSearchState(TypedDict, total=False):
    query: str
    cv_text: str
    preference_memory: str
    clarify_questions: list[str]
    clarify_answers: list[str]
    hits: list[dict]
    refined_query: str | None
    refined_once: bool
    need_refine: bool
    results: list[dict]
```

- [ ] **Step 4: Write `nodes.py`**

```python
# backend/backend/search/advanced/nodes.py
from langgraph.types import interrupt

from backend.search.query_understanding import extract_filters
from backend.search.retrieval import hybrid_retrieve
from backend.search.reranker import rerank
from backend.search.advanced.llm import (
    generate_clarify_questions, critique_results, score_fit,
)


async def node_clarify(state: dict) -> dict:
    questions = await generate_clarify_questions(
        state["query"], state.get("cv_text", ""), state.get("preference_memory", "")
    )
    answers = interrupt({"clarify_questions": questions})
    return {"clarify_questions": questions, "clarify_answers": answers}


async def node_search(state: dict, *, biencoder, reranker, os_client, groq_client) -> dict:
    answers = state.get("clarify_answers") or []
    base_query = state.get("refined_query") or state["query"]
    augmented = (
        f"{base_query}\n"
        f"Clarifications: {' | '.join(str(a) for a in answers)}\n"
        f"Preferences: {state.get('preference_memory', '')}"
    )
    filters = await extract_filters(groq_client, state.get("cv_text", ""), augmented)
    embedding = biencoder.encode(filters.semantic_query).tolist()
    hits = await hybrid_retrieve(os_client, embedding, filters)
    ranked = rerank(reranker, hits, filters.semantic_query)
    return {"hits": ranked}


async def node_critique(state: dict) -> dict:
    if state.get("refined_once"):
        return {"need_refine": False}
    verdict = await critique_results(state["query"], state.get("hits", []))
    if verdict.get("need_refine"):
        return {"need_refine": True, "refined_once": True, "refined_query": verdict.get("refined_query")}
    return {"need_refine": False}


def _route_after_critique(state: dict) -> str:
    return "search" if state.get("need_refine") else "fit_score"


async def node_fit_score(state: dict) -> dict:
    scored = await score_fit(state.get("cv_text", ""), state.get("preference_memory", ""), state.get("hits", []))
    scored.sort(key=lambda r: r.get("fit_score", 0), reverse=True)
    return {"results": scored}
```

- [ ] **Step 5: Write `agent.py`**

```python
# backend/backend/search/advanced/agent.py
from functools import partial
from typing import Any

from langgraph.graph import StateGraph, END

from backend.search.advanced.state import AdvancedSearchState
from backend.search.advanced.nodes import (
    node_clarify, node_search, node_critique, node_fit_score, _route_after_critique,
)


def build_graph(checkpointer, *, biencoder, reranker, os_client, groq_client) -> Any:
    graph = StateGraph(AdvancedSearchState)
    graph.add_node("clarify", node_clarify)
    graph.add_node("search", partial(node_search, biencoder=biencoder, reranker=reranker,
                                      os_client=os_client, groq_client=groq_client))
    graph.add_node("critique", node_critique)
    graph.add_node("fit_score", node_fit_score)
    graph.set_entry_point("clarify")
    graph.add_edge("clarify", "search")
    graph.add_edge("search", "critique")
    graph.add_conditional_edges("critique", _route_after_critique,
                                {"search": "search", "fit_score": "fit_score"})
    graph.add_edge("fit_score", END)
    return graph.compile(checkpointer=checkpointer)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/search/test_advanced_nodes.py -v`
Expected: PASS (7 passed)

- [ ] **Step 7: Commit**

```bash
git add backend/backend/search/advanced/state.py backend/backend/search/advanced/nodes.py backend/backend/search/advanced/agent.py backend/tests/search/test_advanced_nodes.py
git commit -m "feat(search): advanced graph nodes and build_graph"
```

---

### Task 6: Advanced endpoints (`/jobs/search/advanced` + `/resume`)

**Files:**
- Create: `backend/backend/routers/search_advanced.py`
- Modify: `backend/backend/main.py` (make `get_checkpointer` overridable + register router)
- Test: `backend/tests/search/test_advanced_endpoint.py`

**Interfaces:**
- Consumes: `build_graph` (Task 5), `get_memory`/`update_memory_from_session` (Tasks 2/4), `get_biencoder`/`get_reranker`, `get_groq_client`, `get_opensearch`, `get_current_user`, `get_session`, `get_checkpointer`.
- Produces:
  - `POST /jobs/search/advanced` body `{query}` → `{thread_id, clarify_questions}`.
  - `POST /jobs/search/advanced/resume` body `{thread_id, clarify_answers}` → `list[AdvancedJobResult]` (a `JobSearchResponse` plus `fit_score`, `fit_rationale`, `fit_gaps`), sorted by fit score; schedules a background memory distill.

**Note on the checkpointer:** the endpoint takes `checkpointer = Depends(get_checkpointer)` so tests can override it with an in-process `MemorySaver` that persists state across the two HTTP calls.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/search/test_advanced_endpoint.py
import uuid
import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import async_sessionmaker
from langgraph.checkpoint.memory import MemorySaver

from backend.main import app
from backend.routers.search_advanced import get_checkpointer
from backend.database import get_session
from backend.search.models_lifecycle import get_biencoder, get_reranker
from backend.search.query_understanding import get_groq_client
from backend.opensearch_client import get_opensearch
from backend.auth.dependencies import get_current_user
from backend.models import Company, Job, User
from backend.tailorer.models import ApplicantProfile

pytestmark = pytest.mark.asyncio

# NOTE: override the router's get_checkpointer (the dependency the endpoints actually
# use). backend.main.get_checkpointer is a different object and would not take effect.


def _mock_groq(semantic_query="ml engineer"):
    msg = MagicMock(); msg.content = json.dumps({"semantic_query": semantic_query})
    choice = MagicMock(); choice.message = msg
    completion = MagicMock(); completion.choices = [choice]
    client = MagicMock(); client.chat.completions.create.return_value = completion
    return client


@pytest_asyncio.fixture
async def adv_client(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    job_id = uuid.uuid4()
    async with factory() as session:
        session.add(User(id=user_id, username="advuser", password_hash="x"))
        await session.flush()
        session.add(ApplicantProfile(user_id=user_id, cv_text="5yr ML dev"))
        company = Company(name="acme"); session.add(company); await session.flush()
        session.add(Job(id=job_id, url="https://ex.com/1", title="ML Engineer", company_id=company.id))
        await session.commit()
    mock_user = User(id=user_id, username="advuser", password_hash="x")

    async def override_session():
        async with factory() as session:
            yield session

    biencoder = MagicMock()
    enc = MagicMock(); enc.tolist.return_value = [0.0] * 384
    biencoder.encode.return_value = enc
    os_mock = AsyncMock()
    os_mock.search.return_value = {"hits": {"hits": [
        {"_source": {"job_id": str(job_id), "summary_text": "ml engineer"}}
    ]}}

    saver = MemorySaver()

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_biencoder] = lambda: biencoder
    app.dependency_overrides[get_reranker] = lambda: MagicMock()
    app.dependency_overrides[get_groq_client] = lambda: _mock_groq()
    app.dependency_overrides[get_opensearch] = lambda: os_mock
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_checkpointer] = lambda: saver

    with patch("backend.main.init_models"), \
         patch("backend.main.init_opensearch", new_callable=AsyncMock), \
         patch("backend.main.outbox_worker", new_callable=AsyncMock), \
         patch("backend.main._backfill_created_at", new_callable=AsyncMock), \
         patch("backend.search.advanced.nodes.rerank",
               side_effect=lambda r, hits, q, top_k=20: hits), \
         patch("backend.search.advanced.nodes.generate_clarify_questions",
               new=AsyncMock(return_value=["Remote only?"])), \
         patch("backend.search.advanced.nodes.critique_results",
               new=AsyncMock(return_value={"need_refine": False, "refined_query": None})), \
         patch("backend.search.advanced.nodes.score_fit",
               new=AsyncMock(return_value=[{"job_id": str(job_id), "fit_score": 88,
                                            "fit_rationale": "strong", "fit_gaps": "no k8s"}])), \
         patch("backend.search.advanced.preference_memory.distill_memory",
               new=AsyncMock(return_value="prefers remote ml")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac, str(job_id)
    app.dependency_overrides.clear()


async def test_advanced_then_resume_returns_fit_scored(adv_client):
    ac, job_id = adv_client
    start = await ac.post("/jobs/search/advanced", json={"query": "ml engineer"})
    assert start.status_code == 200
    body = start.json()
    assert body["clarify_questions"] == ["Remote only?"]
    thread_id = body["thread_id"]

    resume = await ac.post("/jobs/search/advanced/resume",
                           json={"thread_id": thread_id, "clarify_answers": ["yes"]})
    assert resume.status_code == 200
    results = resume.json()
    assert len(results) == 1
    assert results[0]["id"] == job_id
    assert results[0]["fit_score"] == 88
    assert results[0]["fit_gaps"] == "no k8s"
    assert results[0]["company"]["name"] == "acme"


async def test_advanced_requires_cv(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(User(id=user_id, username="nocv", password_hash="x"))
        await session.commit()
    mock_user = User(id=user_id, username="nocv", password_hash="x")

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_biencoder] = lambda: MagicMock()
    app.dependency_overrides[get_reranker] = lambda: MagicMock()
    app.dependency_overrides[get_groq_client] = lambda: _mock_groq()
    app.dependency_overrides[get_opensearch] = lambda: AsyncMock()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_checkpointer] = lambda: MemorySaver()

    with patch("backend.main.init_models"), \
         patch("backend.main.init_opensearch", new_callable=AsyncMock), \
         patch("backend.main.outbox_worker", new_callable=AsyncMock), \
         patch("backend.main._backfill_created_at", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/jobs/search/advanced", json={"query": "x"})
    app.dependency_overrides.clear()
    assert resp.status_code == 400
    assert "CV" in resp.json()["detail"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/search/test_advanced_endpoint.py -v`
Expected: FAIL with 404 (route not registered)

- [ ] **Step 3: Write the router**

```python
# backend/backend/routers/search_advanced.py
import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from sentence_transformers import SentenceTransformer
from sentence_transformers.cross_encoder import CrossEncoder
from opensearchpy import AsyncOpenSearch
from groq import Groq
from langgraph.types import Command

from backend.database import get_session, get_session_factory
from backend.models import Job, User
from backend.schemas import JobSearchResponse
from backend.search.models_lifecycle import get_biencoder, get_reranker
from backend.search.query_understanding import get_groq_client
from backend.opensearch_client import get_opensearch
from backend.auth.dependencies import get_current_user
from backend.tailorer.models import ApplicantProfile
from backend.search.advanced.agent import build_graph
from backend.search.advanced.preference_memory import get_memory, update_memory_from_session

router = APIRouter(prefix="/jobs/search/advanced", tags=["search-advanced"])
logger = logging.getLogger(__name__)


class AdvancedSearchRequest(BaseModel):
    query: str


class AdvancedSearchStart(BaseModel):
    thread_id: str
    clarify_questions: list[str]


class ResumeRequest(BaseModel):
    thread_id: str
    clarify_answers: list[str]


class AdvancedJobResult(JobSearchResponse):
    fit_score: int
    fit_rationale: str
    fit_gaps: str


async def _load_cv(session: AsyncSession, user: User) -> str:
    result = await session.execute(
        select(ApplicantProfile).where(ApplicantProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile or not profile.cv_text:
        raise HTTPException(status_code=400, detail="No CV uploaded. Please upload your CV first.")
    return profile.cv_text


async def _distill_in_background(user_id: uuid.UUID, query: str, clarify_qa: list[tuple[str, str]]) -> None:
    factory = get_session_factory()
    async with factory() as session:
        try:
            await update_memory_from_session(session, user_id, query, "", clarify_qa)
        except Exception:
            logger.exception("[advanced] memory distill failed")


def get_checkpointer():
    from backend.main import get_checkpointer as _gc
    return _gc()


@router.post("", response_model=AdvancedSearchStart)
async def start_advanced_search(
    body: AdvancedSearchRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    biencoder: SentenceTransformer = Depends(get_biencoder),
    reranker: CrossEncoder = Depends(get_reranker),
    groq_client: Groq = Depends(get_groq_client),
    os_client: AsyncOpenSearch = Depends(get_opensearch),
    checkpointer=Depends(get_checkpointer),
) -> AdvancedSearchStart:
    cv_text = await _load_cv(session, current_user)
    memory = await get_memory(session, current_user.id)

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    graph = build_graph(checkpointer, biencoder=biencoder, reranker=reranker,
                        os_client=os_client, groq_client=groq_client)
    init_state = {
        "query": body.query,
        "cv_text": cv_text,
        "preference_memory": memory.memory_text if memory else "",
        "refined_once": False,
    }
    await graph.ainvoke(init_state, config)
    snap = await graph.aget_state(config)
    interrupts = [i for task in snap.tasks for i in task.interrupts]
    questions = interrupts[0].value.get("clarify_questions", []) if interrupts else []
    return AdvancedSearchStart(thread_id=thread_id, clarify_questions=questions)


@router.post("/resume", response_model=list[AdvancedJobResult])
async def resume_advanced_search(
    body: ResumeRequest,
    background: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    biencoder: SentenceTransformer = Depends(get_biencoder),
    reranker: CrossEncoder = Depends(get_reranker),
    groq_client: Groq = Depends(get_groq_client),
    os_client: AsyncOpenSearch = Depends(get_opensearch),
    checkpointer=Depends(get_checkpointer),
) -> list[AdvancedJobResult]:
    config = {"configurable": {"thread_id": body.thread_id}}
    graph = build_graph(checkpointer, biencoder=biencoder, reranker=reranker,
                        os_client=os_client, groq_client=groq_client)
    await graph.ainvoke(Command(resume=body.clarify_answers), config)
    snap = await graph.aget_state(config)
    values = snap.values or {}
    scored = values.get("results", [])
    if not scored:
        return []

    by_id = {r["job_id"]: r for r in scored}
    result = await session.execute(
        select(Job).options(selectinload(Job.company)).where(Job.id.in_(list(by_id.keys())))
    )
    jobs_by_id = {str(job.id): job for job in result.scalars()}

    response: list[AdvancedJobResult] = []
    for r in scored:  # already sorted by fit_score desc
        job = jobs_by_id.get(r["job_id"])
        if job is None:
            continue
        base = JobSearchResponse.model_validate(job, from_attributes=True)
        response.append(AdvancedJobResult(
            **base.model_dump(),
            fit_score=int(r.get("fit_score", 0)),
            fit_rationale=r.get("fit_rationale", ""),
            fit_gaps=r.get("fit_gaps", ""),
        ))

    questions = values.get("clarify_questions", []) or []
    answers = values.get("clarify_answers", []) or []
    clarify_qa = list(zip(questions, answers))
    background.add_task(_distill_in_background, current_user.id, values.get("query", ""), clarify_qa)

    return response
```

- [ ] **Step 4: Make `get_checkpointer` overridable and register the router in main.py**

In `backend/backend/main.py`, add to the router import block:
```python
from backend.routers.search_advanced import router as search_advanced_router
```
And after `app.include_router(preferences_router)` add:
```python
app.include_router(search_advanced_router)
```
The router defines its own `get_checkpointer` wrapper (importing `backend.main.get_checkpointer` lazily) so `Depends(get_checkpointer)` is overridable in tests via `app.dependency_overrides`. No change to `backend.main.get_checkpointer` itself is required.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/search/test_advanced_endpoint.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Run the full backend search suite to confirm no regressions**

Run: `cd backend && uv run pytest tests/search -v`
Expected: PASS (all, including the unchanged Basic `test_search_endpoint.py`)

- [ ] **Step 7: Commit**

```bash
git add backend/backend/routers/search_advanced.py backend/backend/main.py backend/tests/search/test_advanced_endpoint.py
git commit -m "feat(search): advanced search start/resume endpoints with fit scoring"
```

---

### Task 7: Frontend API client — advanced search + preferences

**Files:**
- Modify: `frontend/src/api/search.ts`
- Create: `frontend/src/api/preferences.ts`

**Interfaces:**
- Produces:
  - `Job` gains optional `fit_score?: number; fit_rationale?: string; fit_gaps?: string`.
  - `startAdvancedSearch(query): Promise<{ thread_id: string; clarify_questions: string[] }>`
  - `resumeAdvancedSearch(threadId, answers): Promise<Job[]>`
  - `getPreferenceMemory(): Promise<{ memory_text: string | null; user_edited: boolean }>`
  - `setPreferenceMemory(text): Promise<{ memory_text: string | null; user_edited: boolean }>`

- [ ] **Step 1: Extend `frontend/src/api/search.ts`**

Add the three fit fields to the `Job` interface (after `company: Company`):
```typescript
  fit_score?: number
  fit_rationale?: string
  fit_gaps?: string
```
Append these exports at the end of the file:
```typescript
export interface AdvancedStart {
  thread_id: string
  clarify_questions: string[]
}

export const startAdvancedSearch = (query: string) =>
  client.post<AdvancedStart>('/jobs/search/advanced', { query }).then(r => r.data)

export const resumeAdvancedSearch = (threadId: string, answers: string[]) =>
  client
    .post<Job[]>('/jobs/search/advanced/resume', { thread_id: threadId, clarify_answers: answers })
    .then(r => r.data)
```

- [ ] **Step 2: Create `frontend/src/api/preferences.ts`**

```typescript
import client from './client'

export interface PreferenceMemory {
  memory_text: string | null
  user_edited: boolean
}

export const getPreferenceMemory = () =>
  client.get<PreferenceMemory>('/me/preference-memory').then(r => r.data)

export const setPreferenceMemory = (memory_text: string) =>
  client.put<PreferenceMemory>('/me/preference-memory', { memory_text }).then(r => r.data)
```

- [ ] **Step 3: Verify the build typechecks**

Run: `cd frontend && npm run build`
Expected: build succeeds (no TS errors)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/search.ts frontend/src/api/preferences.ts
git commit -m "feat(frontend): advanced search + preference memory API client"
```

---

### Task 8: Sidebar component

**Files:**
- Create: `frontend/src/components/Sidebar.tsx`
- Create: `frontend/src/hooks/useSearchMode.ts`
- Test (manual/build): `cd frontend && npm run build`

**Interfaces:**
- Consumes: `me` (`api/auth.ts`), `getPreferenceMemory`/`setPreferenceMemory` (Task 7).
- Produces:
  - `useSearchMode(): { mode: 'basic' | 'advanced'; setMode(m): void }` — persists to `localStorage['search_mode']`.
  - `Sidebar` component: username + logout, nav links (Search / CV), Basic/Advanced toggle, editable preference-memory textarea with Save.

- [ ] **Step 1: Create `frontend/src/hooks/useSearchMode.ts`**

```typescript
import { useState } from 'react'

export type SearchMode = 'basic' | 'advanced'

export function useSearchMode() {
  const [mode, setModeState] = useState<SearchMode>(
    () => (localStorage.getItem('search_mode') as SearchMode) || 'basic',
  )
  const setMode = (m: SearchMode) => {
    localStorage.setItem('search_mode', m)
    setModeState(m)
  }
  return { mode, setMode }
}
```

- [ ] **Step 2: Create `frontend/src/components/Sidebar.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { me, UserResponse } from '../api/auth'
import { getPreferenceMemory, setPreferenceMemory } from '../api/preferences'
import { useSearchMode } from '../hooks/useSearchMode'

export default function Sidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const { mode, setMode } = useSearchMode()
  const [user, setUser] = useState<UserResponse | null>(null)
  const [memory, setMemory] = useState('')
  const [savedNote, setSavedNote] = useState('')

  useEffect(() => {
    me().then(setUser).catch(() => {})
    getPreferenceMemory().then(p => setMemory(p.memory_text || '')).catch(() => {})
  }, [])

  const logout = () => {
    localStorage.removeItem('access_token')
    navigate('/login')
  }

  const saveMemory = async () => {
    await setPreferenceMemory(memory)
    setSavedNote('Saved')
    setTimeout(() => setSavedNote(''), 1500)
  }

  const navLink = (path: string, label: string) => (
    <div
      onClick={() => navigate(path)}
      style={{
        cursor: 'pointer', padding: '0.4rem 0.6rem', borderRadius: 6,
        background: location.pathname === path ? '#2a2a2a' : 'transparent',
      }}
    >
      {label}
    </div>
  )

  return (
    <aside style={{
      width: 240, minWidth: 240, height: '100vh', borderRight: '1px solid #2a2a2a',
      padding: '1rem', display: 'flex', flexDirection: 'column', gap: '1rem', background: '#0f0f0f',
    }}>
      <div style={{ fontWeight: 600 }}>{user?.username || '...'}</div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
        {navLink('/search', 'Search')}
        {navLink('/cv', 'CV')}
      </div>

      <div>
        <div style={{ fontSize: '0.8rem', opacity: 0.6, marginBottom: '0.4rem' }}>Search mode</div>
        <div style={{ display: 'flex', gap: '0.4rem' }}>
          {(['basic', 'advanced'] as const).map(m => (
            <button
              key={m}
              onClick={() => setMode(m)}
              style={{
                flex: 1, padding: '0.35rem', borderRadius: 6,
                background: mode === m ? '#3b82f6' : '#1f1f1f', color: '#fff', border: 'none',
                cursor: 'pointer', textTransform: 'capitalize',
              }}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
        <div style={{ fontSize: '0.8rem', opacity: 0.6 }}>Preferences (learned)</div>
        <textarea
          value={memory}
          onChange={e => setMemory(e.target.value)}
          rows={6}
          style={{ resize: 'vertical', fontSize: '0.8rem', background: '#141414', color: '#eee', border: '1px solid #2a2a2a', borderRadius: 6, padding: '0.4rem' }}
        />
        <button onClick={saveMemory} style={{ padding: '0.35rem', borderRadius: 6, cursor: 'pointer' }}>
          Save preferences
        </button>
        {savedNote && <span style={{ fontSize: '0.75rem', opacity: 0.6 }}>{savedNote}</span>}
      </div>

      <div style={{ marginTop: 'auto', fontSize: '0.85rem', opacity: 0.6, cursor: 'pointer' }} onClick={logout}>
        Logout
      </div>
    </aside>
  )
}
```

- [ ] **Step 3: Verify the build typechecks**

Run: `cd frontend && npm run build`
Expected: build succeeds (no TS errors). (Sidebar is not yet mounted — wired in Task 9.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Sidebar.tsx frontend/src/hooks/useSearchMode.ts
git commit -m "feat(frontend): sidebar with mode toggle and editable preference memory"
```

---

### Task 9: Layout wiring — mount the sidebar around authenticated routes

**Files:**
- Create: `frontend/src/components/AppLayout.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `Sidebar` (Task 8), `PrivateRoute`.
- Produces: `AppLayout` wrapping page content with the sidebar; `/search` and `/cv` render inside it.

- [ ] **Step 1: Create `frontend/src/components/AppLayout.tsx`**

```tsx
import Sidebar from './Sidebar'

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <Sidebar />
      <main style={{ flex: 1, minWidth: 0 }}>{children}</main>
    </div>
  )
}
```

- [ ] **Step 2: Wire it into `frontend/src/App.tsx`**

Replace the file contents with:
```tsx
import { Routes, Route, Navigate } from 'react-router-dom'
import Login from './pages/Login'
import CV from './pages/CV'
import Search from './pages/Search'
import PrivateRoute from './components/PrivateRoute'
import AppLayout from './components/AppLayout'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/cv" element={<PrivateRoute><AppLayout><CV /></AppLayout></PrivateRoute>} />
      <Route path="/search" element={<PrivateRoute><AppLayout><Search /></AppLayout></PrivateRoute>} />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  )
}
```

- [ ] **Step 3: Verify the build typechecks**

Run: `cd frontend && npm run build`
Expected: build succeeds (no TS errors)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/AppLayout.tsx frontend/src/App.tsx
git commit -m "feat(frontend): mount sidebar layout around authenticated routes"
```

---

### Task 10: Search page — advanced clarify→resume flow

**Files:**
- Modify: `frontend/src/pages/Search.tsx`

**Interfaces:**
- Consumes: `searchJobs`, `startAdvancedSearch`, `resumeAdvancedSearch`, `Job` (Task 7); `useSearchMode` (Task 8).
- Produces: when mode is `advanced`, submitting shows the clarify questions, then answering fetches fit-scored results; basic mode keeps current behavior. Remove the inline "Update CV"/"Logout" footer (now in the sidebar).

- [ ] **Step 1: Replace `frontend/src/pages/Search.tsx`**

```tsx
import { useState } from 'react'
import { searchJobs, startAdvancedSearch, resumeAdvancedSearch, Job } from '../api/search'
import { useSearchMode } from '../hooks/useSearchMode'
import JobCard from '../components/JobCard'

export default function Search() {
  const { mode } = useSearchMode()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Job[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [searched, setSearched] = useState(false)

  // advanced clarify state
  const [threadId, setThreadId] = useState<string | null>(null)
  const [questions, setQuestions] = useState<string[]>([])
  const [answers, setAnswers] = useState<string[]>([])

  const resetAdvanced = () => {
    setThreadId(null)
    setQuestions([])
    setAnswers([])
  }

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setResults([])
    resetAdvanced()
    setLoading(true)
    setSearched(true)
    try {
      if (mode === 'basic') {
        setResults(await searchJobs(query))
      } else {
        const start = await startAdvancedSearch(query)
        setThreadId(start.thread_id)
        setQuestions(start.clarify_questions)
        setAnswers(new Array(start.clarify_questions.length).fill(''))
        if (start.clarify_questions.length === 0) {
          setResults(await resumeAdvancedSearch(start.thread_id, []))
          resetAdvanced()
        }
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Search failed')
    } finally {
      setLoading(false)
    }
  }

  async function submitAnswers(e: React.FormEvent) {
    e.preventDefault()
    if (!threadId) return
    setError('')
    setLoading(true)
    try {
      setResults(await resumeAdvancedSearch(threadId, answers))
      resetAdvanced()
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Search failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 720, margin: '4vh auto', padding: '2rem' }}>
      <h2 style={{ marginBottom: '1rem' }}>Search Jobs <span style={{ fontSize: '0.8rem', opacity: 0.5 }}>({mode})</span></h2>

      <form onSubmit={handleSearch} style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem' }}>
        <input value={query} onChange={e => setQuery(e.target.value)} placeholder="e.g. machine learning engineer remote" required />
        <button type="submit" disabled={loading} style={{ whiteSpace: 'nowrap' }}>
          {loading ? '...' : 'Search'}
        </button>
      </form>

      {error && <p style={{ color: '#f87171' }}>{error}</p>}

      {threadId && questions.length > 0 && (
        <form onSubmit={submitAnswers} style={{ margin: '1rem 0', padding: '1rem', border: '1px solid #2a2a2a', borderRadius: 8 }}>
          <div style={{ fontSize: '0.85rem', opacity: 0.7, marginBottom: '0.5rem' }}>A couple quick questions:</div>
          {questions.map((q, i) => (
            <div key={i} style={{ marginBottom: '0.6rem' }}>
              <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '0.2rem' }}>{q}</label>
              <input
                value={answers[i] || ''}
                onChange={e => setAnswers(prev => prev.map((a, j) => (j === i ? e.target.value : a)))}
                style={{ width: '100%' }}
              />
            </div>
          ))}
          <button type="submit" disabled={loading}>{loading ? '...' : 'Continue'}</button>
        </form>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        {results.map(job => <JobCard key={job.id} job={job} />)}
        {searched && !threadId && results.length === 0 && !loading && !error && (
          <p style={{ opacity: 0.4 }}>No results found.</p>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify the build typechecks**

Run: `cd frontend && npm run build`
Expected: build succeeds (no TS errors)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Search.tsx
git commit -m "feat(frontend): advanced clarify-then-results search flow"
```

---

### Task 11: JobCard — show fit score, rationale, and gaps

**Files:**
- Modify: `frontend/src/components/JobCard.tsx`

**Interfaces:**
- Consumes: `Job` with optional `fit_score`/`fit_rationale`/`fit_gaps` (Task 7).
- Produces: a fit badge + rationale + gaps block rendered only when `fit_score` is present (advanced results); basic results are visually unchanged.

- [ ] **Step 1: Add the fit block to `frontend/src/components/JobCard.tsx`**

Immediately after the closing `</div>` of the title line:
```tsx
      <div style={{ fontWeight: 600 }}>{job.title} — {job.company.name}</div>
```
insert:
```tsx
      {typeof job.fit_score === 'number' && (
        <div style={{ marginTop: '0.4rem' }}>
          <span style={{
            fontSize: '0.75rem', fontWeight: 700, padding: '0.15rem 0.5rem', borderRadius: 4,
            background: job.fit_score >= 70 ? '#16653440' : job.fit_score >= 40 ? '#78350f40' : '#7f1d1d40',
            color: job.fit_score >= 70 ? '#4ade80' : job.fit_score >= 40 ? '#fbbf24' : '#f87171',
          }}>
            Fit {job.fit_score}
          </span>
          {job.fit_rationale && (
            <div style={{ fontSize: '0.8rem', opacity: 0.75, marginTop: '0.3rem' }}>{job.fit_rationale}</div>
          )}
          {job.fit_gaps && (
            <div style={{ fontSize: '0.78rem', opacity: 0.55, marginTop: '0.2rem' }}>Gaps: {job.fit_gaps}</div>
          )}
        </div>
      )}
```

- [ ] **Step 2: Verify the build typechecks**

Run: `cd frontend && npm run build`
Expected: build succeeds (no TS errors)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/JobCard.tsx
git commit -m "feat(frontend): show fit score, rationale, and gaps on advanced results"
```

---

## Final verification

- [ ] Run the full backend suite: `cd backend && uv run pytest` — expect all pass.
- [ ] Build the frontend: `cd frontend && npm run build` — expect success.
- [ ] Apply the migration against a dev DB: `cd backend && uv run alembic upgrade head` — expect `009` applied with no error.
