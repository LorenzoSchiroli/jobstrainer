import pytest
from httpx import AsyncClient


async def test_register_returns_token(client: AsyncClient):
    res = await client.post("/auth/register", json={"username": "alice", "password": "secret"})
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


async def test_register_duplicate_username(client: AsyncClient):
    await client.post("/auth/register", json={"username": "bob", "password": "pw"})
    res = await client.post("/auth/register", json={"username": "bob", "password": "other"})
    assert res.status_code == 400


async def test_login_returns_token(client: AsyncClient):
    await client.post("/auth/register", json={"username": "carol", "password": "pass123"})
    res = await client.post("/auth/login", json={"username": "carol", "password": "pass123"})
    assert res.status_code == 200
    assert "access_token" in res.json()


async def test_login_wrong_password(client: AsyncClient):
    await client.post("/auth/register", json={"username": "dave", "password": "correct"})
    res = await client.post("/auth/login", json={"username": "dave", "password": "wrong"})
    assert res.status_code == 401


async def test_me_returns_user(client: AsyncClient):
    reg = await client.post("/auth/register", json={"username": "eve", "password": "pw"})
    token = reg.json()["access_token"]
    res = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["username"] == "eve"
    assert data["has_cv"] is False


async def test_me_no_token(client: AsyncClient):
    res = await client.get("/auth/me")
    assert res.status_code == 401


async def test_me_invalid_token(client: AsyncClient):
    res = await client.get("/auth/me", headers={"Authorization": "Bearer not.a.real.token"})
    assert res.status_code == 401
