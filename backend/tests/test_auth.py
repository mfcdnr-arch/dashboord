"""Аутентификация: вход, неверный пароль, /auth/me, защита без токена."""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import hdr, login


async def test_login_success(client):
    token = await login(client, "admin", "admin")
    assert token


async def test_login_wrong_password(client):
    r = await client.post("/auth/login", data={"username": "admin", "password": "nope"})
    assert r.status_code == 401


async def test_login_unknown_user(client):
    r = await client.post("/auth/login", data={"username": "ztest_nosuch", "password": "x"})
    assert r.status_code == 401


async def test_me_returns_roles(client, admin_headers):
    r = await client.get("/auth/me", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body.get("login") == "admin"
    assert "admin" in (body.get("roles") or [])


async def test_protected_requires_token(client):
    r = await client.get("/dashboards")
    assert r.status_code in (401, 403)


async def test_bad_uuid_returns_400(client, admin_headers):
    # Харденинг: невалидный UUID в пути → чистый 400, не сырой 500.
    r = await client.get("/dashboards/not-a-uuid", headers=admin_headers)
    assert r.status_code == 400
