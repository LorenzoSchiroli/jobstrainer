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
         patch("backend.main.init_opensearch", new_callable=AsyncMock):
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
