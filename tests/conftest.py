import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db import init_db
from app.main import create_app


@pytest_asyncio.fixture
async def client(tmp_path):
    db = tmp_path / "test.db"
    os.environ["DATABASE_PATH"] = str(db)
    init_db(str(db))
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as ac:
        yield ac


@pytest_asyncio.fixture
async def authed(client):
    r = await client.post("/api/login", json={"username": "admin", "password": "123456"})
    assert r.status_code == 200
    return client
