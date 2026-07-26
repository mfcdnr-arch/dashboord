"""Статус первичной настройки (/system/setup-status) для мастера настройки."""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import hdr, login  # noqa: E402
from app import db  # noqa: E402


async def test_setup_status_shape_for_admin(client, admin_headers):
    r = await client.get("/system/setup-status", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    for k in ("departments", "users", "objects", "documents", "datasets", "dashboards", "fresh_install"):
        assert k in body
    assert isinstance(body["fresh_install"], bool)
    assert isinstance(body["users"], int)


async def test_setup_status_requires_auth(client):
    r = await client.get("/system/setup-status")
    assert r.status_code == 401


async def test_setup_status_forbidden_for_regular_user(client, admin_headers):
    """Обычный пользователь (роль user) не видит статус настройки — 403."""
    roles = {x["code"]: x["id"] for x in (await client.get("/roles", headers=admin_headers)).json()}
    try:
        r = await client.post("/users", json={
            "login": "ztest_plain", "password": "Xy345678", "role_ids": [roles["user"]]}, headers=admin_headers)
        assert r.status_code == 201, r.text
        tok = await login(client, "ztest_plain", "Xy345678")
        r = await client.get("/system/setup-status", headers=hdr(tok))
        assert r.status_code == 403
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from user_roles where user_id in (select id from users where login='ztest_plain')")
            await conn.execute("delete from users where login='ztest_plain'")
