"""Роль «Суперадминистратор» и иерархия управления пользователями.

Проверяем: суперадмин может действовать над admin; admin НЕ может трогать
суперадмина и не может выдавать роль superadmin; защита последнего суперадмина;
гибридное удаление (чистого — жёстко; с данными — отказ → блокировка).
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import hdr, login  # noqa: E402
from app import db  # noqa: E402


async def _role_ids(client, headers):
    r = await client.get("/roles", headers=headers)
    assert r.status_code == 200, r.text
    return {x["code"]: x["id"] for x in r.json()}


async def _find_user_id(client, headers, login_name):
    r = await client.get(f"/users?q={login_name}", headers=headers)
    assert r.status_code == 200, r.text
    for u in r.json()["items"]:
        if u["login"] == login_name:
            return u["id"]
    return None


async def _cleanup(logins):
    async with db.acquire() as conn:
        await conn.execute("delete from dashboards where created_by in "
                           "(select id from users where login = any($1::text[]))", logins)
        await conn.execute("delete from user_roles where user_id in "
                           "(select id from users where login = any($1::text[]))", logins)
        await conn.execute("delete from users where login = any($1::text[])", logins)


async def test_superadmin_can_login_and_has_role(client):
    token = await login(client, "superadmin", "superadmin")
    r = await client.get("/auth/me", headers=hdr(token))
    assert r.status_code == 200
    assert "superadmin" in (r.json().get("roles") or [])


async def test_admin_cannot_touch_superadmin(client):
    admin = hdr(await login(client, "admin", "admin"))
    sa_id = await _find_user_id(client, admin, "superadmin")
    assert sa_id
    # блокировка, сброс пароля, удаление суперадмина силами admin — 403
    assert (await client.post(f"/users/{sa_id}/active", json={"is_active": False}, headers=admin)).status_code == 403
    assert (await client.post(f"/users/{sa_id}/reset-password", json={"password": "Xy345678"}, headers=admin)).status_code == 403
    assert (await client.delete(f"/users/{sa_id}", headers=admin)).status_code == 403


async def test_admin_cannot_grant_superadmin_role(client):
    admin = hdr(await login(client, "admin", "admin"))
    roles = await _role_ids(client, admin)
    try:
        # создать пользователя сразу с ролью superadmin — 403 (эскалация)
        r = await client.post("/users", json={
            "login": "ztest_esc", "password": "Xy345678", "role_ids": [roles["superadmin"]]}, headers=admin)
        assert r.status_code == 403, r.text
        # создать обычного и попытаться поднять до superadmin через PATCH — 403
        r = await client.post("/users", json={
            "login": "ztest_esc", "password": "Xy345678", "role_ids": [roles["user"]]}, headers=admin)
        assert r.status_code == 201, r.text
        uid = r.json()["id"]
        r = await client.patch(f"/users/{uid}", json={"role_ids": [roles["superadmin"]]}, headers=admin)
        assert r.status_code == 403, r.text
    finally:
        await _cleanup(["ztest_esc"])


async def test_superadmin_can_manage_admin(client):
    sa = hdr(await login(client, "superadmin", "superadmin"))
    roles = await _role_ids(client, sa)
    try:
        # суперадмин заводит второго администратора
        r = await client.post("/users", json={
            "login": "ztest_admin2", "password": "Xy345678", "role_ids": [roles["admin"]]}, headers=sa)
        assert r.status_code == 201, r.text
        uid = r.json()["id"]
        # суперадмин блокирует и разблокирует этого администратора — можно
        assert (await client.post(f"/users/{uid}/active", json={"is_active": False}, headers=sa)).status_code == 200
        assert (await client.post(f"/users/{uid}/active", json={"is_active": True}, headers=sa)).status_code == 200
        # сброс пароля администратора суперадмином — можно
        assert (await client.post(f"/users/{uid}/reset-password", json={"password": "Zz987654"}, headers=sa)).status_code == 200
    finally:
        await _cleanup(["ztest_admin2"])


async def test_last_superadmin_self_demote_blocked(client):
    """Единственный суперадмин не может снять с себя роль (защита последнего)."""
    sa = hdr(await login(client, "superadmin", "superadmin"))
    roles = await _role_ids(client, sa)
    sa_id = await _find_user_id(client, sa, "superadmin")
    r = await client.patch(f"/users/{sa_id}", json={"role_ids": [roles["user"]]}, headers=sa)
    assert r.status_code == 400, r.text
    assert "суперадмин" in r.json()["detail"].lower()
    # роль на месте
    assert "superadmin" in (await client.get("/auth/me", headers=sa)).json()["roles"]


async def test_hybrid_delete_clean_ok_and_with_data_blocked(client):
    sa = hdr(await login(client, "superadmin", "superadmin"))
    roles = await _role_ids(client, sa)
    try:
        # «чистый» пользователь — жёсткое удаление проходит
        r = await client.post("/users", json={
            "login": "ztest_clean", "password": "Xy345678", "role_ids": [roles["user"]]}, headers=sa)
        assert r.status_code == 201, r.text
        clean_id = r.json()["id"]
        assert (await client.delete(f"/users/{clean_id}", headers=sa)).status_code == 200
        assert await _find_user_id(client, sa, "ztest_clean") is None

        # пользователь с данными (создал дашборд) — удаление запрещено → блокировка
        r = await client.post("/users", json={
            "login": "ztest_creator", "password": "Xy345678", "role_ids": [roles["admin"]]}, headers=sa)
        assert r.status_code == 201, r.text
        creator_id = r.json()["id"]
        async with db.acquire() as conn:
            org = await conn.fetchval("select organization_id from users where id=$1::uuid", creator_id)
            await conn.execute("insert into dashboards(organization_id, name, created_by) values($1,'ztest_dash',$2::uuid)",
                               org, creator_id)
        r = await client.delete(f"/users/{creator_id}", headers=sa)
        assert r.status_code == 400, r.text
        assert "заблокир" in r.json()["detail"].lower()
    finally:
        await _cleanup(["ztest_clean", "ztest_creator"])


async def test_cannot_block_self(client):
    sa = hdr(await login(client, "superadmin", "superadmin"))
    sa_id = await _find_user_id(client, sa, "superadmin")
    r = await client.post(f"/users/{sa_id}/active", json={"is_active": False}, headers=sa)
    assert r.status_code == 400
    assert "себя" in r.json()["detail"]
