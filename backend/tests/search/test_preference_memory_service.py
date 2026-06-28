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
