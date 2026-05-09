import pytest


async def test_create_job_returns_201(client):
    resp = await client.post("/jobs/", json={
        "url": "https://example.com/job/1",
        "title": "ML Engineer",
        "company_name": "Stripe",
        "seniority": "senior",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["url"] == "https://example.com/job/1"
    assert data["title"] == "ML Engineer"
    assert data["seniority"] == "senior"
    assert "id" in data
    assert "company_id" in data


async def test_create_job_auto_creates_company_stub(client):
    resp = await client.post("/jobs/", json={
        "url": "https://example.com/job/2",
        "title": "Data Scientist",
        "company_name": "NewCo",
    })
    assert resp.status_code == 201
    company_id = resp.json()["company_id"]
    company_resp = await client.get(f"/companies/{company_id}")
    assert company_resp.status_code == 200
    assert company_resp.json()["name"] == "newco"


async def test_create_job_links_to_existing_company(client):
    company_resp = await client.post("/companies/", json={"name": "Stripe", "industry": "fintech"})
    company_id = company_resp.json()["id"]

    job_resp = await client.post("/jobs/", json={
        "url": "https://example.com/job/3",
        "title": "Engineer",
        "company_name": "Stripe",
    })
    assert job_resp.status_code == 201
    assert job_resp.json()["company_id"] == company_id


async def test_upsert_job_fills_null_fields(client):
    await client.post("/jobs/", json={
        "url": "https://example.com/job/4",
        "title": "ML Engineer",
        "company_name": "Stripe",
    })
    resp = await client.post("/jobs/", json={
        "url": "https://example.com/job/4",
        "title": "ML Engineer",
        "company_name": "Stripe",
        "seniority": "senior",
        "location": "Berlin",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["seniority"] == "senior"
    assert data["location"] == "Berlin"


async def test_upsert_job_does_not_overwrite_existing_fields(client):
    await client.post("/jobs/", json={
        "url": "https://example.com/job/5",
        "title": "ML Engineer",
        "company_name": "Stripe",
        "seniority": "senior",
    })
    resp = await client.post("/jobs/", json={
        "url": "https://example.com/job/5",
        "title": "ML Engineer",
        "company_name": "Stripe",
        "seniority": "junior",
    })
    assert resp.status_code == 200
    assert resp.json()["seniority"] == "senior"


async def test_get_job_returns_200(client):
    create_resp = await client.post("/jobs/", json={
        "url": "https://example.com/job/6",
        "title": "Engineer",
        "company_name": "Stripe",
    })
    job_id = create_resp.json()["id"]
    resp = await client.get(f"/jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == job_id


async def test_get_job_returns_404_when_not_found(client):
    resp = await client.get("/jobs/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
