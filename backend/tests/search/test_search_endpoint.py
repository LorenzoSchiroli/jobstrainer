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
