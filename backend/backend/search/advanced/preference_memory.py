import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.search.advanced.models import PreferenceMemory
from backend.search.advanced.llm import distill_memory


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
