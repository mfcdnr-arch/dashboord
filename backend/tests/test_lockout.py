"""Блокировка входа после N неудачных попыток (защита от подбора пароля).
Используем уникальный логин, чтобы не заблокировать admin/viewer из других тестов."""
import uuid

import pytest

from app import db

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_lockout_after_n_failures(client):
    login = "ztest_lock_" + uuid.uuid4().hex[:8]
    try:
        # 5 неудач (порог по умолчанию = 5) → каждая 401
        for _ in range(5):
            r = await client.post("/auth/login", data={"username": login, "password": "wrong"})
            assert r.status_code == 401
        # 6-я → блокировка 429
        r = await client.post("/auth/login", data={"username": login, "password": "wrong"})
        assert r.status_code == 429
        assert "попыток" in r.json()["detail"]
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from login_events where login=$1", login)


async def test_normal_login_not_locked(client):
    # обычный успешный вход admin не затронут блокировкой
    r = await client.post("/auth/login", data={"username": "admin", "password": "admin"})
    assert r.status_code == 200
