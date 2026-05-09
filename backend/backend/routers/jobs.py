import uuid
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models import Company, Job
from backend.schemas import JobRequest, JobResponse
from backend.routers.companies import _normalize, _is_empty

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/", response_model=JobResponse, status_code=201)
async def upsert_job(body: JobRequest, response: Response, session: AsyncSession = Depends(get_session)):
    normalized_company = _normalize(body.company_name)
    company_result = await session.execute(select(Company).where(Company.name == normalized_company))
    company = company_result.scalar_one_or_none()
    if company is None:
        company = Company(name=normalized_company)
        session.add(company)

    job_result = await session.execute(select(Job).where(Job.url == body.url))
    job = job_result.scalar_one_or_none()

    if job is None:
        data = body.model_dump(exclude={"company_name"})
        job = Job(company_id=company.id, **data)
        session.add(job)
        response.status_code = 201
    else:
        data = body.model_dump(exclude={"company_name", "url"})
        for field, value in data.items():
            if not _is_empty(value) and _is_empty(getattr(job, field)):
                setattr(job, field, value)
        response.status_code = 200

    await session.commit()
    await session.refresh(job)
    return job


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="not found")
    return job
