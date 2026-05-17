from unittest.mock import AsyncMock
from sqlalchemy import select
from backend.models import Outbox, Job, Company
from backend.outbox.worker import process_pending_events


async def _company(session, name="Acme") -> Company:
    c = Company(name=name)
    session.add(c)
    await session.flush()
    return c


async def _job(session, company_id, url="https://ex.com/1") -> Job:
    j = Job(url=url, title="Engineer", company_id=company_id)
    session.add(j)
    await session.flush()
    return j


async def test_job_event_indexes_in_opensearch(db_session):
    company = await _company(db_session)
    job = await _job(db_session, company.id)
    db_session.add(Outbox(event_type="job_upserted", entity_id=job.id, payload={"embedding": [0.1] * 384}))
    await db_session.commit()

    mock_os = AsyncMock()
    await process_pending_events(db_session, mock_os)

    mock_os.index.assert_called_once()
    kwargs = mock_os.index.call_args.kwargs
    assert kwargs["id"] == str(job.id)
    assert kwargs["body"]["embedding"] == [0.1] * 384

    result = await db_session.execute(select(Outbox))
    event = result.scalar_one()
    assert event.processed_at is not None


async def test_company_event_calls_update_by_query(db_session):
    company = await _company(db_session, "TestCo")
    db_session.add(Outbox(event_type="company_upserted", entity_id=company.id, payload={}))
    await db_session.commit()

    mock_os = AsyncMock()
    await process_pending_events(db_session, mock_os)

    mock_os.update_by_query.assert_called_once()
    result = await db_session.execute(select(Outbox))
    assert result.scalar_one().processed_at is not None


async def test_opensearch_failure_leaves_event_unprocessed(db_session):
    company = await _company(db_session, "FailCo")
    job = await _job(db_session, company.id, "https://ex.com/fail")
    db_session.add(Outbox(event_type="job_upserted", entity_id=job.id, payload={}))
    await db_session.commit()

    mock_os = AsyncMock()
    mock_os.index.side_effect = Exception("OpenSearch down")
    await process_pending_events(db_session, mock_os)

    result = await db_session.execute(select(Outbox))
    assert result.scalar_one().processed_at is None
