import pytest
import uuid
from unittest.mock import patch, AsyncMock, MagicMock
from starlette.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
import os

from backend.main import app
from backend.database import get_session
from backend.auth.jwt import create_access_token


DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/jobsifty_test",
)


@pytest.mark.asyncio
async def test_handle_interrupt_apply_fills_sends_commands_and_returns_response():
    """apply_fills forwards commands to WS and returns the extension's response."""
    from backend.tailorer.router import _handle_interrupt

    ws = AsyncMock()
    extension_response = {"type": "fills_applied", "results": []}
    ws.receive_json = AsyncMock(return_value=extension_response)

    interrupt_val = {
        "type": "apply_fills",
        "commands": [
            {"index": 2, "value": "John", "action": "input_text"},
            {"index": 5, "value": "Engineer", "action": "input_text"},
        ],
    }

    result = await _handle_interrupt(ws, interrupt_val, thread_id="t1", token="tok")

    ws.send_json.assert_called_once()
    sent = ws.send_json.call_args[0][0]
    assert sent["type"] == "apply_fills"
    assert sent["commands"] == interrupt_val["commands"]
    assert sent["thread_id"] == "t1"
    assert sent["token"] == "tok"
    assert result == extension_response


@pytest.mark.asyncio
async def test_handle_interrupt_unknown_type_returns_unknown():
    """Unknown interrupt types log a warning and return {type: unknown}."""
    from backend.tailorer.router import _handle_interrupt

    ws = AsyncMock()

    interrupt_val = {"type": "some_future_type", "data": "x"}

    result = await _handle_interrupt(ws, interrupt_val)

    ws.send_json.assert_not_called()
    assert result == {"type": "unknown"}


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
             patch("backend.main.init_opensearch", new_callable=AsyncMock):
            with TestClient(app) as tc:
                with pytest.raises(Exception):
                    with tc.websocket_connect(f"/tailorer/ws/{job_id}"):
                        pass
    finally:
        app.dependency_overrides.clear()
