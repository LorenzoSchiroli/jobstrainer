from httpx import AsyncClient


async def _token(client: AsyncClient, username: str = "u1") -> str:
    res = await client.post("/auth/register", json={"username": username, "password": "pw"})
    return res.json()["access_token"]


async def test_get_cv_empty(client: AsyncClient):
    token = await _token(client)
    res = await client.get("/users/cv", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json() == {"cv_text": None, "has_cv": False}


async def test_upload_txt(client: AsyncClient):
    token = await _token(client, "u2")
    content = b"Software engineer with 5 years Python experience."
    res = await client.post(
        "/users/cv",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("cv.txt", content, "text/plain")},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["char_count"] == len(content)
    assert data["message"] == "CV uploaded successfully"


async def test_get_cv_after_upload(client: AsyncClient):
    token = await _token(client, "u3")
    content = b"Backend developer skilled in Go and Python."
    await client.post(
        "/users/cv",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("cv.txt", content, "text/plain")},
    )
    res = await client.get("/users/cv", headers={"Authorization": f"Bearer {token}"})
    assert res.json()["has_cv"] is True
    assert "Backend developer" in res.json()["cv_text"]


async def test_upload_replaces_previous(client: AsyncClient):
    token = await _token(client, "u4")
    await client.post("/users/cv", headers={"Authorization": f"Bearer {token}"}, files={"file": ("old.txt", b"old cv", "text/plain")})
    await client.post("/users/cv", headers={"Authorization": f"Bearer {token}"}, files={"file": ("new.txt", b"new cv content", "text/plain")})
    res = await client.get("/users/cv", headers={"Authorization": f"Bearer {token}"})
    assert res.json()["cv_text"] == "new cv content"


async def test_upload_unsupported_format(client: AsyncClient):
    token = await _token(client, "u5")
    res = await client.post(
        "/users/cv",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("cv.xlsx", b"data", "application/vnd.ms-excel")},
    )
    assert res.status_code == 400


async def test_upload_requires_auth(client: AsyncClient):
    res = await client.post("/users/cv", files={"file": ("cv.txt", b"text", "text/plain")})
    assert res.status_code == 401
