"""Отзыв ранее выданных JWT при смене/сбросе пароля (миграция 033).

До этого токен жил до истечения срока независимо от смены пароля: при
компрометации приходилось блокировать учётную запись (финальный аудит, С-1).
"""
import time

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

import pytest_asyncio

from app import db
from app.modules.auth.security import hash_password


@pytest_asyncio.fixture
async def temp_user(client, admin_headers, ids):
    """Обычный пользователь с известным паролем и уже пройденной сменой."""
    login, pwd = "ztest_revoke", "RevokeAudit2026"
    async with db.acquire() as conn:
        await conn.execute("delete from user_roles where user_id in (select id from users where login=$1)", login)
        await conn.execute("delete from users where login=$1", login)
        uid = await conn.fetchval(
            "insert into users(organization_id, login, full_name, password_hash, is_active, must_change_password) "
            "values($1,$2,'Тест отзыва',$3,true,false) returning id",
            ids["org"], login, hash_password(pwd))
        role = await conn.fetchval("select id from roles where code='user' and organization_id=$1", ids["org"])
        if role:
            await conn.execute("insert into user_roles(user_id, role_id) values($1,$2)", uid, role)
    yield {"id": str(uid), "login": login, "password": pwd}
    async with db.acquire() as conn:
        await conn.execute("delete from user_roles where user_id=$1", uid)
        await conn.execute("delete from login_events where user_id=$1", uid)
        await conn.execute("delete from users where id=$1", uid)


async def _login(client, login, password):
    r = await client.post("/auth/login", data={"username": login, "password": password})
    return r.json()["access_token"] if r.status_code == 200 else None


async def test_self_change_password_revokes_old_token_and_returns_new(client, temp_user):
    old = await _login(client, temp_user["login"], temp_user["password"])
    assert old
    # Гарантия отзыва — посекундная (iat в JWT целочисленный), поэтому токен
    # должен быть выпущен в ПРЕДЫДУЩУЮ секунду относительно смены пароля.
    time.sleep(1.1)
    old_h = {"Authorization": f"Bearer {old}"}
    assert (await client.get("/auth/me", headers=old_h)).status_code == 200

    r = await client.post("/auth/change-password", headers=old_h, json={"new_password": "RevokeAudit2026b"})
    assert r.status_code == 200, r.text
    fresh = r.json().get("access_token")
    assert fresh, "смена пароля должна вернуть новый токен взамен отозванного"

    # старый токен больше не работает, новый — работает
    assert (await client.get("/auth/me", headers=old_h)).status_code == 401
    assert (await client.get("/auth/me", headers={"Authorization": f"Bearer {fresh}"})).status_code == 200


async def test_admin_reset_password_revokes_user_sessions(client, admin_headers, temp_user):
    tok = await _login(client, temp_user["login"], temp_user["password"])
    assert tok
    time.sleep(1.1)  # см. комментарий выше — отзыв посекундный
    h = {"Authorization": f"Bearer {tok}"}
    assert (await client.get("/auth/me", headers=h)).status_code == 200

    r = await client.post(f"/users/{temp_user['id']}/reset-password", headers=admin_headers,
                          json={"password": "AdminReset2026"})
    assert r.status_code == 200, r.text
    assert (await client.get("/auth/me", headers=h)).status_code == 401
