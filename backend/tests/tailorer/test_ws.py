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
    "postgresql+asyncpg://postgres:postgres@localhost:5432/jobstrainer_test",
)


@pytest.mark.asyncio
async def test_handle_interrupt_execute_actions_returns_snapshot():
    """execute_actions sends actions to WS and returns the snapshot response."""
    from backend.tailorer.router import _handle_interrupt

    ws = AsyncMock()
    snapshot = {"url": "https://example.com", "title": "Test", "elements": "[1]<button >Apply />", "scroll_y": 0, "scroll_height": 100, "viewport_height": 800}
    ws.receive_json = AsyncMock(return_value=snapshot)

    interrupt_val = {
        "type": "execute_actions",
        "actions": [
            {"action": "click_element", "index": 1},
        ]
    }

    result = await _handle_interrupt(ws, interrupt_val)

    ws.send_json.assert_called()
    sent = ws.send_json.call_args[0][0]
    assert sent["type"] == "execute_actions"
    assert sent["actions"] == [{"action": "click_element", "index": 1}]
    assert result == snapshot


@pytest.mark.asyncio
async def test_handle_interrupt_fill_and_confirm_sends_index_commands():
    """fill_and_confirm sends index-based commands and show_confirm with file_links."""
    from backend.tailorer.router import _handle_interrupt

    ws = AsyncMock()
    ws.receive_json = AsyncMock(return_value={"type": "user_approved"})

    interrupt_val = {
        "type": "fill_and_confirm",
        "commands": [
            {"index": 2, "value": "John", "action": "input_text", "uncertain": False},
            {"index": 7, "value": "__CV__", "action": "file_upload"},
        ],
        "summary": "Filling page 1",
    }

    result = await _handle_interrupt(ws, interrupt_val, thread_id="t1", token="tok")

    calls = [c[0][0] for c in ws.send_json.call_args_list]
    # Regular fill command sent first
    assert any(c.get("action") == "input_text" for c in calls)
    # show_confirm sent with file_links
    confirm_call = next(c for c in calls if c.get("type") == "show_confirm")
    assert len(confirm_call["file_links"]) == 1
    assert confirm_call["file_links"][0]["field_id"] == 7
    assert result == {"type": "user_approved"}


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
