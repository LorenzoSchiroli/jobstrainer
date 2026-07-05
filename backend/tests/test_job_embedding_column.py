from backend.models import Company, Job


async def test_job_row_persists_embedding(db_session):
    company = Company(name="acme")
    db_session.add(company)
    await db_session.flush()

    job = Job(url="https://example.com/embed-1", title="Engineer", company_id=company.id, embedding=[0.1, 0.2, 0.3])
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    assert job.embedding == [0.1, 0.2, 0.3]


async def test_job_row_embedding_defaults_to_none(db_session):
    company = Company(name="acme2")
    db_session.add(company)
    await db_session.flush()

    job = Job(url="https://example.com/embed-2", title="Engineer", company_id=company.id)
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    assert job.embedding is None
