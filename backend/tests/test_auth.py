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


async def test_must_change_password_blocks_api(client, admin_headers):
    """Пользователь с временным паролем не может пользоваться API, пока не сменит
    пароль: всё, кроме /auth/me и /auth/change-password, → 403."""
    from conftest import hdr  # noqa: E402
    from app import db  # noqa: E402
    roles = {x["code"]: x["id"] for x in (await client.get("/roles", headers=admin_headers)).json()}
    try:
        await client.post("/users", json={
            "login": "ztest_tmp", "password": "Xy345678", "role_ids": [roles["user"]]}, headers=admin_headers)
        tok = hdr(await login(client, "ztest_tmp", "Xy345678"))
        # защищённый эндпоинт заблокирован до смены пароля
        r = await client.get("/dashboards", headers=tok)
        assert r.status_code == 403
        assert "смените" in r.json()["detail"].lower()
        # свой профиль и смена пароля — разрешены
        assert (await client.get("/auth/me", headers=tok)).status_code == 200
        assert (await client.post("/auth/change-password", json={"new_password": "NewPass99"}, headers=tok)).status_code == 200
        # после смены — доступ восстановлен
        tok2 = hdr(await login(client, "ztest_tmp", "NewPass99"))
        assert (await client.get("/dashboards", headers=tok2)).status_code == 200
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from user_roles where user_id in (select id from users where login='ztest_tmp')")
            await conn.execute("delete from users where login='ztest_tmp'")
