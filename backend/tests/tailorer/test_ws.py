import pytest
import uuid
from unittest.mock import patch, AsyncMock
from starlette.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
import os

from backend.main import app
from backend.database import get_session
from backend.auth.jwt import create_access_token


DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/jobstrainer_test",
)


def test_ws_rejects_missing_token():
    """WebSocket without token param gets closed immediately."""
    engine = create_async_engine(DATABASE_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    job_id = str(uuid.uuid4())
    try:
        with patch("backend.main.init_models"), \
             patch("backend.main.init_opensearch", new_callable=AsyncMock), \
             patch("backend.main._backfill_created_at", new_callable=AsyncMock), \
             patch("backend.main.outbox_worker", new_callable=AsyncMock):
            with TestClient(app) as tc:
                with pytest.raises(Exception):
                    with tc.websocket_connect(f"/tailorer/ws/{job_id}"):
                        pass
    finally:
        app.dependency_overrides.clear()
