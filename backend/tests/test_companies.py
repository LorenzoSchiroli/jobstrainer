import pytest


async def test_create_company_returns_201(client):
    resp = await client.post("/companies/", json={"name": "Stripe", "industry": "fintech"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "stripe"
    assert data["industry"] == "fintech"
    assert "id" in data


async def test_create_company_normalizes_name(client):
    resp = await client.post("/companies/", json={"name": "  Stripe  "})
    assert resp.status_code == 201
    assert resp.json()["name"] == "stripe"


async def test_upsert_company_fills_null_fields(client):
    await client.post("/companies/", json={"name": "Stripe"})
    resp = await client.post("/companies/", json={"name": "Stripe", "industry": "fintech", "country": "US"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["industry"] == "fintech"
    assert data["country"] == "US"


async def test_upsert_company_does_not_overwrite_existing_fields(client):
    await client.post("/companies/", json={"name": "Stripe", "industry": "fintech"})
    resp = await client.post("/companies/", json={"name": "Stripe", "industry": "payments"})
    assert resp.status_code == 200
    assert resp.json()["industry"] == "fintech"


async def test_get_company_returns_200(client):
    create_resp = await client.post("/companies/", json={"name": "Stripe"})
    company_id = create_resp.json()["id"]
    resp = await client.get(f"/companies/{company_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == company_id


async def test_get_company_returns_404_when_not_found(client):
    resp = await client.get("/companies/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
