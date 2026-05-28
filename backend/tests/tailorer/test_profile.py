import pytest
from httpx import AsyncClient
from backend.auth.jwt import create_access_token


@pytest.fixture
async def auth_headers(client, db_session):
    from backend.models import User
    from passlib.context import CryptContext
    pwd = CryptContext(schemes=["bcrypt"])
    user = User(username="tester", password_hash=pwd.hash("pw"))
    db_session.add(user)
    await db_session.commit()
    token = create_access_token(str(user.id))
    return {"Authorization": f"Bearer {token}"}


async def test_get_profile_empty(client: AsyncClient, auth_headers):
    r = await client.get("/tailorer/profile", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["first_name"] is None
    assert data["has_cv"] is False


async def test_upsert_profile(client: AsyncClient, auth_headers):
    payload = {
        "first_name": "Lorenzo",
        "last_name": "Schiroli",
        "email": "l@example.com",
        "phone": "+39123",
        "city": "Milan",
        "country": "Italy",
        "work_auth": "EU citizen",
        "urls": {"linkedin": "https://linkedin.com/in/test"},
        "extra_qa": {"notice_period": "2 weeks"},
    }
    r = await client.put("/tailorer/profile", headers=auth_headers, json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["first_name"] == "Lorenzo"
    assert data["last_name"] == "Schiroli"
    assert data["urls"]["linkedin"] == "https://linkedin.com/in/test"

    # Idempotent: second upsert updates
    r2 = await client.put("/tailorer/profile", headers=auth_headers,
                          json={**payload, "city": "Rome"})
    assert r2.status_code == 200
    assert r2.json()["city"] == "Rome"
