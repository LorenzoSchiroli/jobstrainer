from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models import User
from backend.auth.dependencies import get_current_user
from backend.search.advanced.preference_memory import get_memory, set_memory

router = APIRouter(prefix="/me", tags=["preferences"])


class PreferenceMemoryResponse(BaseModel):
    memory_text: str | None
    user_edited: bool


class PreferenceMemoryUpdate(BaseModel):
    memory_text: str


@router.get("/preference-memory", response_model=PreferenceMemoryResponse)
async def read_preference_memory(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PreferenceMemoryResponse:
    pm = await get_memory(session, current_user.id)
    if pm is None:
        return PreferenceMemoryResponse(memory_text=None, user_edited=False)
    return PreferenceMemoryResponse(memory_text=pm.memory_text, user_edited=pm.user_edited)


@router.put("/preference-memory", response_model=PreferenceMemoryResponse)
async def write_preference_memory(
    body: PreferenceMemoryUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PreferenceMemoryResponse:
    pm = await set_memory(session, current_user.id, body.memory_text)
    return PreferenceMemoryResponse(memory_text=pm.memory_text, user_edited=pm.user_edited)
