import asyncio
import logging
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from opensearchpy import AsyncOpenSearch

from backend.database import get_session_factory
from backend.models import Outbox, Job, Company
from backend.opensearch_client import get_opensearch, INDEX_NAME

logger = logging.getLogger(__name__)


def _flatten_summary(summary: dict | None) -> str:
    if not summary:
        return ""
    parts = (
        summary.get("role_info", []) +
        summary.get("requirements", []) +
        summary.get("responsibilities", []) +
        summary.get("domain", [])
    )
    return " ".join(parts)


def _build_job_doc(job: Job, embedding: list[float] | None) -> dict:
    c = job.company
    return {
        "job_id": str(job.id),
        "company_id": str(job.company_id),
        "title": job.title,
        "description": job.description or "",
        "summary_text": _flatten_summary(job.summary),
        "embedding": embedding,
        "employment_type": job.employment_type,
        "location_type": job.location_type,
        "seniority": job.seniority,
        "languages_required": job.languages_required or [],
        "is_consulting": c.is_consulting if c else None,
        "is_startup": c.is_startup if c else None,
        "industry": c.industry if c else None,
        "country": c.country if c else None,
        "review_score": c.review_score if c else None,
        "financial_health_score": c.financial_health_score if c else None,
        "created_at": job.created_at.isoformat(),
    }


async def _handle_job_upserted(event: Outbox, session: AsyncSession, os_client: AsyncOpenSearch) -> None:
    result = await session.execute(
        select(Job).options(selectinload(Job.company)).where(Job.id == event.entity_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        return
    doc = _build_job_doc(job, event.payload.get("embedding"))
    await os_client.index(index=INDEX_NAME, id=str(job.id), body=doc)


async def _handle_company_upserted(event: Outbox, session: AsyncSession, os_client: AsyncOpenSearch) -> None:
    result = await session.execute(select(Company).where(Company.id == event.entity_id))
    company = result.scalar_one_or_none()
    if company is None:
        return
    await os_client.update_by_query(
        index=INDEX_NAME,
        body={
            "script": {
                "source": (
                    "ctx._source.is_consulting = params.is_consulting;"
                    "ctx._source.is_startup = params.is_startup;"
                    "ctx._source.industry = params.industry;"
                    "ctx._source.country = params.country;"
                    "ctx._source.review_score = params.review_score;"
                    "ctx._source.financial_health_score = params.financial_health_score;"
                ),
                "params": {
                    "is_consulting": company.is_consulting,
                    "is_startup": company.is_startup,
                    "industry": company.industry,
                    "country": company.country,
                    "review_score": company.review_score,
                    "financial_health_score": company.financial_health_score,
                },
            },
            "query": {"term": {"company_id": str(company.id)}},
        },
    )


async def process_pending_events(session: AsyncSession, os_client: AsyncOpenSearch) -> None:
    result = await session.execute(
        select(Outbox)
        .where(Outbox.processed_at.is_(None))
        .order_by(Outbox.created_at)
        .limit(100)
    )
    events = result.scalars().all()
    for event in events:
        try:
            if event.event_type == "job_upserted":
                await _handle_job_upserted(event, session, os_client)
            elif event.event_type == "company_upserted":
                await _handle_company_upserted(event, session, os_client)
            event.processed_at = datetime.now(timezone.utc)
        except Exception as e:
            logger.warning("Outbox event %s failed: %s", event.id, e)
    if events:
        await session.commit()


async def outbox_worker() -> None:
    factory = get_session_factory()
    while True:
        try:
            os_client = get_opensearch()
            async with factory() as session:
                await process_pending_events(session, os_client)
        except Exception as e:
            logger.warning("Outbox worker error: %s", e)
        await asyncio.sleep(1)
