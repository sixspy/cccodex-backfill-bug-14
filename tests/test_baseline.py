import pytest


@pytest.mark.asyncio
async def test_login_page(client):
    r = await client.get("/login")
    assert r.status_code == 200
    assert "密码" in r.text or "登录" in r.text


@pytest.mark.asyncio
async def test_login_ok(client):
    r = await client.post("/api/login", json={"username": "admin", "password": "123456"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
