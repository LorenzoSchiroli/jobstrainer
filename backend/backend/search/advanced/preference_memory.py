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
