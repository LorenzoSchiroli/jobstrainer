import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from opensearchpy import AsyncOpenSearch
from opensearchpy.helpers import async_bulk

from backend.database import get_session_factory
from backend.models import Outbox, Job, Company
from backend.opensearch_client import get_opensearch, get_existing_job_ids, INDEX_NAME

logger = logging.getLogger(__name__)

RECONCILE_INTERVAL_SECONDS = 300
RETENTION_INTERVAL_SECONDS = 21600
RECONCILE_BATCH_SIZE = 2000
RECONCILE_WINDOW_DAYS = 30
RETENTION_MAX_AGE_DAYS = 30


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


def _build_job_doc(job: Job) -> dict:
    c = job.company
    return {
        "job_id": str(job.id),
        "company_id": str(job.company_id),
        "title": job.title,
        "description": job.description or "",
        "summary_text": _flatten_summary(job.summary),
        "embedding": job.embedding,
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


async def reconcile(
    session: AsyncSession,
    os_client: AsyncOpenSearch,
    batch_size: int = RECONCILE_BATCH_SIZE,
) -> int:
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=RECONCILE_WINDOW_DAYS)

    # 1. Changed entities: everything with an unprocessed outbox row.
    events = (
        await session.execute(select(Outbox).where(Outbox.processed_at.is_(None)))
    ).scalars().all()
    changed_job_ids = {e.entity_id for e in events if e.event_type == "job_upserted"}
    company_events = [e for e in events if e.event_type == "company_upserted"]

    # 2. Missing entities: live jobs (created within the window) absent from OpenSearch.
    live_ids = [
        str(jid)
        for (jid,) in (
            await session.execute(select(Job.id).where(Job.created_at >= window_start))
        ).all()
    ]
    present = await get_existing_job_ids(os_client, live_ids)
    missing_ids = {uuid.UUID(i) for i in set(live_ids) - present}

    # 3. Union, newest-first, capped. Re-index from Postgres via the bulk API.
    to_index = changed_job_ids | missing_ids
    indexed_ids: set[uuid.UUID] = set()
    if to_index:
        jobs = (
            await session.execute(
                select(Job)
                .options(selectinload(Job.company))
                .where(Job.id.in_(to_index))
                .order_by(Job.created_at.desc())
                .limit(batch_size)
            )
        ).scalars().all()
        if jobs:
            actions = [
                {"_index": INDEX_NAME, "_id": str(j.id), "_source": _build_job_doc(j)}
                for j in jobs
            ]
            await async_bulk(os_client, actions)
            indexed_ids = {j.id for j in jobs}

    # 4. Company changes: patch derived fields on their jobs' docs.
    for event in company_events:
        try:
            await _handle_company_upserted(event, session, os_client)
        except Exception as e:
            logger.warning("Company reconcile %s failed: %s", event.entity_id, e)
            continue
        event.processed_at = now

    # 5. Stamp job events whose job was actually indexed this pass (capped-out
    #    ones stay unprocessed and are retried next tick).
    for event in events:
        if event.event_type == "job_upserted" and event.entity_id in indexed_ids:
            event.processed_at = now

    if events:
        await session.commit()
    return len(indexed_ids)
