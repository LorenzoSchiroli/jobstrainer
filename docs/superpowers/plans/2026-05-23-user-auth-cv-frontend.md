# User Auth, CV Upload & React Frontend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add user auth (JWT), CV upload/storage, update search to use saved CV, and build a Vite + React frontend with login, CV upload, and search pages.

**Architecture:** Auth integrated into existing FastAPI backend; new `users` table in Postgres stores credentials and extracted CV text. The frontend is a separate Vite + React app (port 3000) served by nginx in Docker.

**Tech Stack:** Python: python-jose[cryptography], passlib[bcrypt], python-multipart, pdfplumber, python-docx. Frontend: Vite 5, React 18, TypeScript, react-router-dom 6, axios.

---

## File Map

**Backend — New:**
- `backend/backend/auth/__init__.py`
- `backend/backend/auth/jwt.py` — create/decode JWT tokens
- `backend/backend/auth/dependencies.py` — `get_current_user` FastAPI dependency
- `backend/backend/routers/auth.py` — register, login, me endpoints
- `backend/backend/routers/cv.py` — CV upload/get endpoints
- `backend/alembic/versions/006_users.py` — migration adding users table
- `backend/tests/test_jwt.py` — unit tests for JWT utility
- `backend/tests/test_auth.py` — integration tests for auth routes
- `backend/tests/test_cv.py` — integration tests for CV routes

**Backend — Modified:**
- `backend/backend/models.py` — add User model
- `backend/backend/main.py` — CORS + new routers
- `backend/backend/routers/search.py` — remove cv_text, add auth dependency
- `backend/pyproject.toml` — add new deps
- `backend/tests/conftest.py` — add SECRET_KEY env var
- `backend/tests/search/test_search_endpoint.py` — update for auth

**Frontend — New:**
- `frontend/package.json`
- `frontend/vite.config.ts`
- `frontend/tsconfig.json`
- `frontend/index.html`
- `frontend/.env`
- `frontend/Dockerfile`
- `frontend/nginx.conf`
- `frontend/src/main.tsx`
- `frontend/src/App.tsx`
- `frontend/src/index.css`
- `frontend/src/api/client.ts`
- `frontend/src/api/auth.ts`
- `frontend/src/api/cv.ts`
- `frontend/src/api/search.ts`
- `frontend/src/components/PrivateRoute.tsx`
- `frontend/src/components/JobCard.tsx`
- `frontend/src/pages/Login.tsx`
- `frontend/src/pages/CV.tsx`
- `frontend/src/pages/Search.tsx`

**Infrastructure — Modified:**
- `docker-compose.yml` — frontend service + SECRET_KEY for backend
- `.env.example` — SECRET_KEY
- `.gitignore` — .superpowers/

---

## Task 1: Add backend dependencies

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `.env.example`

- [ ] **Step 1: Add dependencies to pyproject.toml**

Replace the `dependencies` list in `backend/pyproject.toml`:

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
    "torch>=2.0.0",
    "python-jose[cryptography]>=3.3.0",
    "passlib[bcrypt]>=1.7.4",
    "python-multipart>=0.0.9",
    "pdfplumber>=0.11.0",
    "python-docx>=1.1.0",
]
```

- [ ] **Step 2: Install dependencies**

```bash
cd backend
uv sync
```

Expected: resolves and installs without errors.

- [ ] **Step 3: Update .env.example**

Add to `.env.example`:

```
SECRET_KEY=change-me-generate-with-python-secrets
ACCESS_TOKEN_EXPIRE_DAYS=7
```

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml .env.example
git commit -m "chore(backend): add auth and file extraction dependencies"
```

---

## Task 2: User model and Alembic migration

**Files:**
- Modify: `backend/backend/models.py`
- Create: `backend/alembic/versions/006_users.py`

- [ ] **Step 1: Add User to models.py**

In `backend/backend/models.py`, add the `User` class after the imports and before `class Company`:

```python
class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    cv_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
```

- [ ] **Step 2: Create migration 006_users.py**

Create `backend/alembic/versions/006_users.py`:

```python
"""add users table

Revision ID: 006
Revises: 005
Create Date: 2026-05-23
"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("cv_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )


def downgrade() -> None:
    op.drop_table("users")
```

- [ ] **Step 3: Apply migration (skip if postgres not running locally)**

```bash
cd backend
uv run alembic upgrade head
```

Expected: `Running upgrade 005 -> 006` with no errors. The Docker compose startup applies this automatically if skipped.

- [ ] **Step 4: Commit**

```bash
git add backend/backend/models.py backend/alembic/versions/006_users.py
git commit -m "feat(backend): add User model and users table migration"
```

---

## Task 3: JWT utility

**Files:**
- Create: `backend/backend/auth/__init__.py`
- Create: `backend/backend/auth/jwt.py`
- Create: `backend/tests/test_jwt.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_jwt.py`:

```python
import os
os.environ.setdefault("SECRET_KEY", "test-secret")

import pytest
from jose import JWTError
from backend.auth.jwt import create_access_token, decode_access_token


def test_create_and_decode_roundtrip():
    token = create_access_token("user-id-123")
    assert decode_access_token(token) == "user-id-123"


def test_decode_invalid_token_raises():
    with pytest.raises(JWTError):
        decode_access_token("not.a.valid.token")


def test_decode_tampered_token_raises():
    token = create_access_token("user-id-456")
    tampered = token[:-4] + "XXXX"
    with pytest.raises(JWTError):
        decode_access_token(tampered)
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend
uv run pytest tests/test_jwt.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.auth'`

- [ ] **Step 3: Create auth module**

Create `backend/backend/auth/__init__.py` (empty file).

Create `backend/backend/auth/jwt.py`:

```python
import os
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError  # noqa: F401

ALGORITHM = "HS256"


def _secret() -> str:
    return os.environ["SECRET_KEY"]


def _expire_days() -> int:
    return int(os.getenv("ACCESS_TOKEN_EXPIRE_DAYS", "7"))


def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=_expire_days())
    return jwt.encode({"sub": user_id, "exp": expire}, _secret(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> str:
    payload = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    return payload["sub"]
```

- [ ] **Step 4: Run to verify passing**

```bash
cd backend
uv run pytest tests/test_jwt.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/backend/auth/__init__.py backend/backend/auth/jwt.py backend/tests/test_jwt.py
git commit -m "feat(backend): add JWT create/decode utility"
```

---

## Task 4: Auth dependency + routes (register, login, me)

**Files:**
- Create: `backend/backend/auth/dependencies.py`
- Create: `backend/backend/routers/auth.py`
- Modify: `backend/tests/conftest.py`
- Create: `backend/tests/test_auth.py`
- Modify: `backend/backend/main.py`

- [ ] **Step 1: Add SECRET_KEY to test conftest**

In `backend/tests/conftest.py`, add after the first `import os` line:

```python
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/jobstrainer_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
```

(The rest of the file stays unchanged.)

- [ ] **Step 2: Write failing tests**

Create `backend/tests/test_auth.py`:

```python
import pytest
from httpx import AsyncClient


async def test_register_returns_token(client: AsyncClient):
    res = await client.post("/auth/register", json={"username": "alice", "password": "secret"})
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


async def test_register_duplicate_username(client: AsyncClient):
    await client.post("/auth/register", json={"username": "bob", "password": "pw"})
    res = await client.post("/auth/register", json={"username": "bob", "password": "other"})
    assert res.status_code == 400


async def test_login_returns_token(client: AsyncClient):
    await client.post("/auth/register", json={"username": "carol", "password": "pass123"})
    res = await client.post("/auth/login", json={"username": "carol", "password": "pass123"})
    assert res.status_code == 200
    assert "access_token" in res.json()


async def test_login_wrong_password(client: AsyncClient):
    await client.post("/auth/register", json={"username": "dave", "password": "correct"})
    res = await client.post("/auth/login", json={"username": "dave", "password": "wrong"})
    assert res.status_code == 401


async def test_me_returns_user(client: AsyncClient):
    reg = await client.post("/auth/register", json={"username": "eve", "password": "pw"})
    token = reg.json()["access_token"]
    res = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["username"] == "eve"
    assert data["has_cv"] is False


async def test_me_no_token(client: AsyncClient):
    res = await client.get("/auth/me")
    assert res.status_code == 401


async def test_me_invalid_token(client: AsyncClient):
    res = await client.get("/auth/me", headers={"Authorization": "Bearer not.a.real.token"})
    assert res.status_code == 401
```

- [ ] **Step 3: Run to verify failure**

```bash
cd backend
uv run pytest tests/test_auth.py -v
```

Expected: all fail with 404 (routes don't exist yet).

- [ ] **Step 4: Create auth/dependencies.py**

Create `backend/backend/auth/dependencies.py`:

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import JWTError

from backend.database import get_session
from backend.models import User
from backend.auth.jwt import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        user_id = decode_access_token(token)
    except JWTError:
        raise exc
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise exc
    return user
```

- [ ] **Step 5: Create routers/auth.py**

Create `backend/backend/routers/auth.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from passlib.context import CryptContext

from backend.database import get_session
from backend.models import User
from backend.auth.jwt import create_access_token
from backend.auth.dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    username: str
    has_cv: bool


@router.post("/register", response_model=TokenResponse)
async def register(body: AuthRequest, session: AsyncSession = Depends(get_session)):
    existing = await session.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already taken")
    user = User(username=body.username, password_hash=_pwd.hash(body.password))
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return TokenResponse(access_token=create_access_token(str(user.id)))


@router.post("/login", response_model=TokenResponse)
async def login(body: AuthRequest, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    if not user or not _pwd.verify(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return TokenResponse(access_token=create_access_token(str(user.id)))


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=str(current_user.id),
        username=current_user.username,
        has_cv=current_user.cv_text is not None,
    )
```

- [ ] **Step 6: Register auth router in main.py**

In `backend/backend/main.py`, add the import and include:

```python
from backend.routers.auth import router as auth_router

# add after existing app.include_router lines:
app.include_router(auth_router)
```

- [ ] **Step 7: Run to verify passing**

```bash
cd backend
uv run pytest tests/test_auth.py -v
```

Expected: 7 passed.

- [ ] **Step 8: Commit**

```bash
git add backend/backend/auth/dependencies.py backend/backend/routers/auth.py backend/backend/main.py backend/tests/conftest.py backend/tests/test_auth.py
git commit -m "feat(backend): add user auth routes (register, login, me)"
```

---

## Task 5: CV upload and retrieval routes

**Files:**
- Create: `backend/backend/routers/cv.py`
- Create: `backend/tests/test_cv.py`
- Modify: `backend/backend/main.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_cv.py`:

```python
from httpx import AsyncClient


async def _token(client: AsyncClient, username: str = "u1") -> str:
    res = await client.post("/auth/register", json={"username": username, "password": "pw"})
    return res.json()["access_token"]


async def test_get_cv_empty(client: AsyncClient):
    token = await _token(client)
    res = await client.get("/users/cv", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json() == {"cv_text": None, "has_cv": False}


async def test_upload_txt(client: AsyncClient):
    token = await _token(client, "u2")
    content = b"Software engineer with 5 years Python experience."
    res = await client.post(
        "/users/cv",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("cv.txt", content, "text/plain")},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["char_count"] == len(content)
    assert data["message"] == "CV uploaded successfully"


async def test_get_cv_after_upload(client: AsyncClient):
    token = await _token(client, "u3")
    content = b"Backend developer skilled in Go and Python."
    await client.post(
        "/users/cv",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("cv.txt", content, "text/plain")},
    )
    res = await client.get("/users/cv", headers={"Authorization": f"Bearer {token}"})
    assert res.json()["has_cv"] is True
    assert "Backend developer" in res.json()["cv_text"]


async def test_upload_replaces_previous(client: AsyncClient):
    token = await _token(client, "u4")
    await client.post("/users/cv", headers={"Authorization": f"Bearer {token}"}, files={"file": ("old.txt", b"old cv", "text/plain")})
    await client.post("/users/cv", headers={"Authorization": f"Bearer {token}"}, files={"file": ("new.txt", b"new cv content", "text/plain")})
    res = await client.get("/users/cv", headers={"Authorization": f"Bearer {token}"})
    assert res.json()["cv_text"] == "new cv content"


async def test_upload_unsupported_format(client: AsyncClient):
    token = await _token(client, "u5")
    res = await client.post(
        "/users/cv",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("cv.xlsx", b"data", "application/vnd.ms-excel")},
    )
    assert res.status_code == 400


async def test_upload_requires_auth(client: AsyncClient):
    res = await client.post("/users/cv", files={"file": ("cv.txt", b"text", "text/plain")})
    assert res.status_code == 401
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend
uv run pytest tests/test_cv.py -v
```

Expected: all fail with 404.

- [ ] **Step 3: Create routers/cv.py**

Create `backend/backend/routers/cv.py`:

```python
import io
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from backend.database import get_session
from backend.models import User
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
    current_user.cv_text = text
    session.add(current_user)
    await session.commit()
    return CVUploadResponse(message="CV uploaded successfully", char_count=len(text))


@router.get("/cv", response_model=CVResponse)
async def get_cv(current_user: User = Depends(get_current_user)):
    return CVResponse(cv_text=current_user.cv_text, has_cv=current_user.cv_text is not None)
```

- [ ] **Step 4: Register cv router in main.py**

In `backend/backend/main.py`, add:

```python
from backend.routers.cv import router as cv_router

# add after auth_router line:
app.include_router(cv_router)
```

- [ ] **Step 5: Run to verify passing**

```bash
cd backend
uv run pytest tests/test_cv.py -v
```

Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/backend/routers/cv.py backend/backend/main.py backend/tests/test_cv.py
git commit -m "feat(backend): add CV upload and retrieval routes"
```

---

## Task 6: Update search endpoint to use saved CV

**Files:**
- Modify: `backend/backend/routers/search.py`
- Modify: `backend/tests/search/test_search_endpoint.py`

- [ ] **Step 1: Replace search endpoint tests**

Replace the full contents of `backend/tests/search/test_search_endpoint.py`:

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
from backend.auth.dependencies import get_current_user
from backend.models import Company, Job, User


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


def _mock_user(cv_text: str | None = "5yr Python dev") -> User:
    return User(id=uuid.uuid4(), username="testuser", password_hash="x", cv_text=cv_text)


@pytest_asyncio.fixture
async def search_client(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():
        async with factory() as session:
            yield session

    mock_biencoder = MagicMock()
    encode_result = MagicMock()
    encode_result.tolist.return_value = [0.0] * 384
    mock_biencoder.encode.return_value = encode_result
    mock_reranker = MagicMock()
    mock_reranker.predict.return_value = [0.9]
    mock_os = AsyncMock()

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_biencoder] = lambda: mock_biencoder
    app.dependency_overrides[get_reranker] = lambda: mock_reranker
    app.dependency_overrides[get_groq_client] = lambda: _mock_groq()
    app.dependency_overrides[get_opensearch] = lambda: mock_os
    app.dependency_overrides[get_current_user] = lambda: _mock_user()

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

    resp = await ac.post("/jobs/search", json={"query": "ml engineer"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == str(job_id)
    assert data[0]["company"]["name"] == "acme"


async def test_search_returns_empty_list_when_no_hits(search_client):
    ac, mock_os, _ = search_client
    mock_os.search.return_value = {"hits": {"hits": []}}
    resp = await ac.post("/jobs/search", json={"query": "q"})
    assert resp.status_code == 200
    assert resp.json() == []


async def test_search_returns_400_when_no_cv(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_biencoder] = lambda: MagicMock()
    app.dependency_overrides[get_reranker] = lambda: MagicMock()
    app.dependency_overrides[get_groq_client] = lambda: _mock_groq()
    app.dependency_overrides[get_opensearch] = lambda: AsyncMock()
    app.dependency_overrides[get_current_user] = lambda: _mock_user(cv_text=None)

    with patch("backend.main.init_models"), \
         patch("backend.main.init_opensearch", new_callable=AsyncMock), \
         patch("backend.main.outbox_worker", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/jobs/search", json={"query": "ml engineer"})

    app.dependency_overrides.clear()
    assert resp.status_code == 400
    assert "CV" in resp.json()["detail"]
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend
uv run pytest tests/search/test_search_endpoint.py -v
```

Expected: `test_search_returns_200_with_ranked_jobs` and `test_search_returns_empty_list_when_no_hits` fail because the endpoint still requires `cv_text`; `test_search_returns_400_when_no_cv` fails because the endpoint isn't auth-protected yet.

- [ ] **Step 3: Replace routers/search.py**

Replace the full contents of `backend/backend/routers/search.py`:

```python
import logging
import time
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from sentence_transformers import SentenceTransformer
from sentence_transformers.cross_encoder import CrossEncoder
from opensearchpy import AsyncOpenSearch
from pydantic import BaseModel
from groq import Groq

from backend.database import get_session
from backend.models import Job, User
from backend.schemas import JobSearchResponse
from backend.search.filters import SearchFilters
from backend.search.models_lifecycle import get_biencoder, get_reranker
from backend.search.query_understanding import extract_filters, get_groq_client
from backend.search.retrieval import hybrid_retrieve
from backend.search.reranker import rerank
from backend.opensearch_client import get_opensearch
from backend.auth.dependencies import get_current_user

router = APIRouter(prefix="/jobs", tags=["search"])
logger = logging.getLogger(__name__)


class SearchRequest(BaseModel):
    query: str
    strict: bool = False


@router.post("/search", response_model=list[JobSearchResponse])
async def search_jobs(
    body: SearchRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    biencoder: SentenceTransformer = Depends(get_biencoder),
    reranker: CrossEncoder = Depends(get_reranker),
    groq_client: Groq = Depends(get_groq_client),
    os_client: AsyncOpenSearch = Depends(get_opensearch),
) -> list[JobSearchResponse]:
    if not current_user.cv_text:
        raise HTTPException(status_code=400, detail="No CV uploaded. Please upload your CV first.")

    t0 = time.perf_counter()

    filters: SearchFilters = await extract_filters(groq_client, current_user.cv_text, body.query)
    t1 = time.perf_counter()

    query_embedding: list[float] = biencoder.encode(filters.semantic_query).tolist()
    t2 = time.perf_counter()

    hits = await hybrid_retrieve(os_client, query_embedding, filters, strict=body.strict)
    t3 = time.perf_counter()

    ranked_hits = rerank(reranker, hits, filters.semantic_query)
    t4 = time.perf_counter()

    if not ranked_hits:
        logger.info("[search timing] query_understanding=%.3fs embed=%.3fs retrieve=%.3fs rerank=%.3fs total=%.3fs (no hits)", t1-t0, t2-t1, t3-t2, t4-t3, t4-t0)
        return []

    ranked_ids = [hit["_source"]["job_id"] for hit in ranked_hits]
    result = await session.execute(
        select(Job).options(selectinload(Job.company)).where(Job.id.in_(ranked_ids))
    )
    t5 = time.perf_counter()

    logger.info("[search timing] query_understanding=%.3fs embed=%.3fs retrieve=%.3fs rerank=%.3fs db=%.3fs total=%.3fs", t1-t0, t2-t1, t3-t2, t4-t3, t5-t4, t5-t0)

    jobs_by_id = {str(job.id): job for job in result.scalars()}
    return [jobs_by_id[id_] for id_ in ranked_ids if id_ in jobs_by_id]
```

- [ ] **Step 4: Run all backend tests**

```bash
cd backend
uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/backend/routers/search.py backend/tests/search/test_search_endpoint.py
git commit -m "feat(backend): search endpoint requires auth and reads CV from DB"
```

---

## Task 7: CORS, router wiring, and gitignore

**Files:**
- Modify: `backend/backend/main.py`
- Modify: `.gitignore`

- [ ] **Step 1: Replace main.py with final version**

Replace the full contents of `backend/backend/main.py`:

```python
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

from backend.routers import companies, jobs
from backend.routers.search import router as search_router
from backend.routers.auth import router as auth_router
from backend.routers.cv import router as cv_router
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(companies.router)
app.include_router(jobs.router)
app.include_router(search_router)
app.include_router(auth_router)
app.include_router(cv_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    import traceback
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"detail": "internal server error"})
```

- [ ] **Step 2: Add .superpowers/ to .gitignore**

Append to `.gitignore`:

```
.superpowers/
```

- [ ] **Step 3: Run full test suite**

```bash
cd backend
uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/backend/main.py .gitignore
git commit -m "feat(backend): add CORS middleware and wire all routers"
```

---

## Task 8: Frontend scaffold

**Files:** All new under `frontend/`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p frontend/src/api frontend/src/pages frontend/src/components
```

- [ ] **Step 2: Create package.json**

Create `frontend/package.json`:

```json
{
  "name": "jobstrainer-frontend",
  "private": true,
  "version": "0.1.0",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "axios": "^1.7.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "react-router-dom": "^6.24.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "typescript": "^5.5.0",
    "vite": "^5.3.0"
  }
}
```

- [ ] **Step 3: Create vite.config.ts**

Create `frontend/vite.config.ts`:

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
})
```

- [ ] **Step 4: Create tsconfig.json**

Create `frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true
  },
  "include": ["src"]
}
```

- [ ] **Step 5: Create index.html**

Create `frontend/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>jobstrainer</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 6: Create .env for local dev**

Create `frontend/.env`:

```
VITE_API_URL=http://localhost:8000
```

- [ ] **Step 7: Create nginx.conf**

Create `frontend/nginx.conf`:

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

- [ ] **Step 8: Create Dockerfile**

Create `frontend/Dockerfile`:

```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

- [ ] **Step 9: Install npm dependencies**

```bash
cd frontend
npm install
```

Expected: `node_modules/` created, `package-lock.json` generated.

- [ ] **Step 10: Create src/index.css**

Create `frontend/src/index.css`:

```css
*, *::before, *::after { box-sizing: border-box; }

body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: #0f0f0f;
  color: #e5e5e5;
  font-size: 16px;
  line-height: 1.5;
}

input {
  background: #1a1a1a;
  border: 1px solid #333;
  color: #e5e5e5;
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  font-size: 1rem;
  width: 100%;
}

input:focus { outline: none; border-color: #555; }

button {
  background: #2a2a2a;
  border: 1px solid #444;
  color: #e5e5e5;
  padding: 0.5rem 1rem;
  border-radius: 6px;
  font-size: 1rem;
  cursor: pointer;
}

button:hover:not(:disabled) { background: #333; }
button:disabled { opacity: 0.5; cursor: not-allowed; }
```

- [ ] **Step 11: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): scaffold Vite + React app with Dockerfile and nginx"
```

---

## Task 9: API client layer

**Files:** New under `frontend/src/api/`

- [ ] **Step 1: Create api/client.ts**

Create `frontend/src/api/client.ts`:

```typescript
import axios from 'axios'

const client = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
})

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

export default client
```

- [ ] **Step 2: Create api/auth.ts**

Create `frontend/src/api/auth.ts`:

```typescript
import client from './client'

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface UserResponse {
  id: string
  username: string
  has_cv: boolean
}

export const login = (username: string, password: string) =>
  client.post<TokenResponse>('/auth/login', { username, password }).then(r => r.data)

export const register = (username: string, password: string) =>
  client.post<TokenResponse>('/auth/register', { username, password }).then(r => r.data)

export const me = () =>
  client.get<UserResponse>('/auth/me').then(r => r.data)
```

- [ ] **Step 3: Create api/cv.ts**

Create `frontend/src/api/cv.ts`:

```typescript
import client from './client'

export interface CVResponse {
  cv_text: string | null
  has_cv: boolean
}

export interface CVUploadResponse {
  message: string
  char_count: number
}

export const uploadCV = (file: File) => {
  const form = new FormData()
  form.append('file', file)
  return client.post<CVUploadResponse>('/users/cv', form).then(r => r.data)
}

export const getCV = () =>
  client.get<CVResponse>('/users/cv').then(r => r.data)
```

- [ ] **Step 4: Create api/search.ts**

Create `frontend/src/api/search.ts`:

```typescript
import client from './client'

export interface Company {
  name: string
  country: string | null
  is_consulting: boolean | null
  is_startup: boolean | null
  financial_health_score: number | null
  industry: string | null
}

export interface Job {
  id: string
  title: string
  url: string
  location: string | null
  employment_type: string | null
  location_type: string | null
  seniority: string | null
  languages_required: string[]
  company: Company
}

export const searchJobs = (query: string, strict: boolean) =>
  client.post<Job[]>('/jobs/search', { query, strict }).then(r => r.data)
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/
git commit -m "feat(frontend): add typed API client layer (auth, cv, search)"
```

---

## Task 10: PrivateRoute and App router

**Files:**
- Create: `frontend/src/components/PrivateRoute.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/main.tsx`

- [ ] **Step 1: Create PrivateRoute.tsx**

Create `frontend/src/components/PrivateRoute.tsx`:

```typescript
import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { me } from '../api/auth'

export default function PrivateRoute({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<'loading' | 'ok' | 'unauthorized'>('loading')

  useEffect(() => {
    const token = localStorage.getItem('access_token')
    if (!token) { setStatus('unauthorized'); return }
    me().then(() => setStatus('ok')).catch(() => {
      localStorage.removeItem('access_token')
      setStatus('unauthorized')
    })
  }, [])

  if (status === 'loading') return null
  if (status === 'unauthorized') return <Navigate to="/login" replace />
  return <>{children}</>
}
```

- [ ] **Step 2: Create App.tsx**

Create `frontend/src/App.tsx`:

```typescript
import { Routes, Route, Navigate } from 'react-router-dom'
import Login from './pages/Login'
import CV from './pages/CV'
import Search from './pages/Search'
import PrivateRoute from './components/PrivateRoute'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/cv" element={<PrivateRoute><CV /></PrivateRoute>} />
      <Route path="/search" element={<PrivateRoute><Search /></PrivateRoute>} />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  )
}
```

- [ ] **Step 3: Create main.tsx**

Create `frontend/src/main.tsx`:

```typescript
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
)
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/PrivateRoute.tsx frontend/src/App.tsx frontend/src/main.tsx
git commit -m "feat(frontend): add PrivateRoute guard and top-level router"
```

---

## Task 11: Login page

**Files:**
- Create: `frontend/src/pages/Login.tsx`

- [ ] **Step 1: Create Login.tsx**

Create `frontend/src/pages/Login.tsx`:

```typescript
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login, register, me } from '../api/auth'

export default function Login() {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const fn = mode === 'login' ? login : register
      const { access_token } = await fn(username, password)
      localStorage.setItem('access_token', access_token)
      const user = await me()
      navigate(user.has_cv ? '/search' : '/cv')
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 360, margin: '10vh auto', padding: '2rem' }}>
      <h1 style={{ textAlign: 'center', marginBottom: '2rem', fontSize: '1.5rem' }}>jobstrainer</h1>
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        <input
          value={username}
          onChange={e => setUsername(e.target.value)}
          placeholder="Username"
          autoComplete="username"
          required
        />
        <input
          type="password"
          value={password}
          onChange={e => setPassword(e.target.value)}
          placeholder="Password"
          autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
          required
        />
        {error && <p style={{ color: '#f87171', margin: 0, fontSize: '0.875rem' }}>{error}</p>}
        <button type="submit" disabled={loading}>
          {loading ? 'Loading...' : mode === 'login' ? 'Login' : 'Register'}
        </button>
        <button
          type="button"
          onClick={() => { setMode(m => m === 'login' ? 'register' : 'login'); setError('') }}
          style={{ background: 'none', border: 'none', cursor: 'pointer', opacity: 0.5, fontSize: '0.875rem' }}
        >
          {mode === 'login' ? 'No account? Register' : 'Have an account? Login'}
        </button>
      </form>
    </div>
  )
}
```

- [ ] **Step 2: Verify in browser**

```bash
cd frontend && npm run dev
```

Open http://localhost:5173. You should see the login form. Try registering — you should be redirected to `/cv`. Try wrong password — an error message should appear.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Login.tsx
git commit -m "feat(frontend): add login/register page"
```

---

## Task 12: CV upload page

**Files:**
- Create: `frontend/src/pages/CV.tsx`

- [ ] **Step 1: Create CV.tsx**

Create `frontend/src/pages/CV.tsx`:

```typescript
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { uploadCV, getCV } from '../api/cv'

export default function CV() {
  const [hasCV, setHasCV] = useState(false)
  const [charCount, setCharCount] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [uploading, setUploading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()

  useEffect(() => {
    getCV().then(({ has_cv, cv_text }) => {
      setHasCV(has_cv)
      if (cv_text) setCharCount(cv_text.length)
    }).catch(() => {})
  }, [])

  async function handleFile(file: File) {
    setError('')
    setUploading(true)
    try {
      const res = await uploadCV(file)
      setHasCV(true)
      setCharCount(res.char_count)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  return (
    <div style={{ maxWidth: 480, margin: '10vh auto', padding: '2rem' }}>
      <h2>Your CV</h2>

      {hasCV && (
        <p style={{ opacity: 0.6, fontSize: '0.875rem' }}>
          CV loaded ({charCount?.toLocaleString()} characters). Upload a new file to replace it.
        </p>
      )}

      <div
        onDrop={e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) handleFile(f) }}
        onDragOver={e => e.preventDefault()}
        onClick={() => inputRef.current?.click()}
        style={{
          border: '2px dashed #444',
          borderRadius: 8,
          padding: '3rem',
          textAlign: 'center',
          cursor: 'pointer',
          marginBottom: '1rem',
        }}
      >
        {uploading ? 'Uploading...' : 'Drop PDF / DOCX / TXT here or click to browse'}
      </div>

      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.docx,.txt"
        style={{ display: 'none' }}
        onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f) }}
      />

      {error && <p style={{ color: '#f87171', fontSize: '0.875rem' }}>{error}</p>}

      <div style={{ display: 'flex', gap: '1rem', marginTop: '1rem' }}>
        <button onClick={() => navigate('/search')} disabled={!hasCV} style={{ flex: 1 }}>
          Go to Search →
        </button>
        <button
          onClick={() => { localStorage.removeItem('access_token'); navigate('/login') }}
          style={{ opacity: 0.5 }}
        >
          Logout
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify in browser**

With `npm run dev` and backend running: log in, navigate to `/cv`, upload a `.txt` file. The char count should appear and "Go to Search" should become enabled. Try drag-and-drop as well.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/CV.tsx
git commit -m "feat(frontend): add CV upload page with drag-and-drop"
```

---

## Task 13: Search page and JobCard

**Files:**
- Create: `frontend/src/pages/Search.tsx`
- Create: `frontend/src/components/JobCard.tsx`

- [ ] **Step 1: Create JobCard.tsx**

Create `frontend/src/components/JobCard.tsx`:

```typescript
import { Job } from '../api/search'

export default function JobCard({ job }: { job: Job }) {
  const tags = [
    job.employment_type,
    job.location_type,
    job.seniority,
    ...job.languages_required,
  ].filter(Boolean) as string[]

  return (
    <a
      href={job.url}
      target="_blank"
      rel="noopener noreferrer"
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

- [ ] **Step 2: Create Search.tsx**

Create `frontend/src/pages/Search.tsx`:

```typescript
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { searchJobs, Job } from '../api/search'
import JobCard from '../components/JobCard'

export default function Search() {
  const [query, setQuery] = useState('')
  const [strict, setStrict] = useState(false)
  const [results, setResults] = useState<Job[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [searched, setSearched] = useState(false)
  const navigate = useNavigate()

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    setSearched(true)
    try {
      setResults(await searchJobs(query, strict))
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Search failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 720, margin: '4vh auto', padding: '2rem' }}>
      <h2 style={{ marginBottom: '1rem' }}>Search Jobs</h2>

      <form onSubmit={handleSearch} style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem' }}>
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="e.g. machine learning engineer remote"
          required
        />
        <button type="submit" disabled={loading} style={{ whiteSpace: 'nowrap' }}>
          {loading ? '...' : 'Search'}
        </button>
      </form>

      <label style={{ fontSize: '0.875rem', opacity: 0.6, display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '1.5rem' }}>
        <input type="checkbox" checked={strict} onChange={e => setStrict(e.target.checked)} />
        Strict mode
      </label>

      {error && <p style={{ color: '#f87171' }}>{error}</p>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        {results.map(job => <JobCard key={job.id} job={job} />)}
        {searched && results.length === 0 && !loading && !error && (
          <p style={{ opacity: 0.4 }}>No results found.</p>
        )}
      </div>

      <div style={{ marginTop: '2rem', fontSize: '0.8rem', opacity: 0.4, display: 'flex', gap: '1.5rem' }}>
        <span style={{ cursor: 'pointer' }} onClick={() => navigate('/cv')}>Update CV</span>
        <span style={{ cursor: 'pointer' }} onClick={() => { localStorage.removeItem('access_token'); navigate('/login') }}>Logout</span>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Verify in browser**

With `npm run dev` and backend running: log in with a user that has a CV, search for a query. Job cards should appear, each clickable. Test strict mode and logout.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Search.tsx frontend/src/components/JobCard.tsx
git commit -m "feat(frontend): add search page and job card component"
```

---

## Task 14: Docker wiring

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Update docker-compose.yml**

Replace the full contents of `docker-compose.yml`:

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
      - discovery.type=single-node
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
      GROQ_MODEL_LARGE: ${GROQ_MODEL_LARGE}
      GROQ_MODEL_BASE: ${GROQ_MODEL_BASE}
      SECRET_KEY: ${SECRET_KEY}
      ACCESS_TOKEN_EXPIRE_DAYS: ${ACCESS_TOKEN_EXPIRE_DAYS:-7}
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
      GROQ_MODEL_LARGE: ${GROQ_MODEL_LARGE}
      GROQ_MODEL_BASE: ${GROQ_MODEL_BASE}
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

  frontend:
    build:
      context: ./frontend
      args:
        VITE_API_URL: http://localhost:8000
    ports:
      - "3000:80"
    depends_on:
      - backend

volumes:
  postgres_data:
```

- [ ] **Step 2: Add SECRET_KEY to local .env**

Generate a secret key and add it to your local `.env`:

```bash
python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"
```

Copy the output line into `.env`.

- [ ] **Step 3: Verify Docker build**

```bash
docker compose build
```

Expected: all images build without errors.

- [ ] **Step 4: Verify full stack**

```bash
docker compose up -d postgres opensearch
# wait ~15s for healthy status, then:
docker compose up backend frontend
```

Open http://localhost:3000 — register a user, upload a CV, run a search.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(docker): add frontend service and SECRET_KEY to backend"
```
