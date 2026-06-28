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
