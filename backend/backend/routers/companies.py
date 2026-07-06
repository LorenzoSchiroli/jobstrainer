import uuid
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models import Company, Outbox
from backend.schemas import CompanyRequest, CompanyResponse

router = APIRouter(prefix="/companies", tags=["companies"])


def _normalize(name: str) -> str:
    return name.lower().strip()


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, list) and not value:
        return True
    return False


@router.post("/", response_model=CompanyResponse, status_code=201)
async def upsert_company(body: CompanyRequest, response: Response, session: AsyncSession = Depends(get_session)):
    normalized = _normalize(body.name)
    result = await session.execute(select(Company).where(Company.name == normalized))
    company = result.scalar_one_or_none()

    if company is None:
        data = body.model_dump()
        data["name"] = normalized
        company = Company(**data)
        session.add(company)
        response.status_code = 201
    else:
        data = body.model_dump(exclude={"name"})
        for field, value in data.items():
            if not _is_empty(value) and _is_empty(getattr(company, field)):
                setattr(company, field, value)
        response.status_code = 200

    await session.flush()

    session.add(Outbox(
        event_type="company_upserted",
        entity_id=company.id,
    ))

    await session.commit()
    await session.refresh(company)
    return company


@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company(company_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Company).where(Company.id == company_id))
    company = result.scalar_one_or_none()
    if company is None:
        raise HTTPException(status_code=404, detail="not found")
    return company
