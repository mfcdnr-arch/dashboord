"""Обращения пользователей к администратору/модератору (волна C).

Проверяем: создание/список/ответ/закрытие, разграничение доступа (чужое
обращение — 404, статистика/список всех — только staff), обращение при
заблокированном аккаунте (без JWT, различение «заблокирован» от «неверный
пароль», отсутствие утечки существования логина)."""
import uuid

import pytest

from app import db
from app.modules.auth.security import hash_password
from conftest import hdr, login

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _purge_appeal(appeal_id):
    async with db.acquire() as conn:
        await conn.execute("delete from appeals where id=$1::uuid", appeal_id)


async def test_appeal_create_reply_close_flow(client, admin_headers, viewer):
    r = await client.post("/appeals", headers=viewer["headers"], json={"subject": "Тест", "body": "Не работает выгрузка"})
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    try:
        # viewer видит своё в /appeals/mine
        r = await client.get("/appeals/mine", headers=viewer["headers"])
        assert r.status_code == 200
        assert any(i["id"] == aid and i["status"] == "open" for i in r.json()["items"])

        # admin видит в общем списке + счётчике открытых
        r = await client.get("/appeals", headers=admin_headers)
        assert any(i["id"] == aid for i in r.json()["items"])
        r = await client.get("/appeals/stats", headers=admin_headers)
        assert r.json()["open"] >= 1

        # создание обращения попадает в аудит (актор — автор, entity_type=appeal)
        async with db.acquire() as conn:
            row = await conn.fetchrow(
                "select action, actor_user_id from audit_log where entity_type='appeal' and entity_id=$1::uuid "
                "and action='create'", aid)
        assert row is not None and str(row["actor_user_id"]) == viewer["id"]

        # admin отвечает → статус answered, viewer получает уведомление appeal.replied
        r = await client.post(f"/appeals/{aid}/messages", headers=admin_headers, json={"body": "Проверяем"})
        assert r.status_code == 201
        assert r.json()["status"] == "answered"
        r = await client.get("/notifications", headers=viewer["headers"])
        assert any(n["event_type"] == "appeal.replied" and n["entity_id"] == aid for n in r.json()["items"])

        # ответ staff тоже в аудите (action=update, новый статус в new_data)
        async with db.acquire() as conn:
            n_updates = await conn.fetchval(
                "select count(*) from audit_log where entity_type='appeal' and entity_id=$1::uuid and action='update'", aid)
        assert n_updates >= 1

        # viewer читает тред целиком (2 сообщения, в порядке создания)
        r = await client.get(f"/appeals/{aid}", headers=viewer["headers"])
        assert r.status_code == 200
        msgs = r.json()["messages"]
        assert len(msgs) == 2 and msgs[0]["is_staff"] is False and msgs[1]["is_staff"] is True

        # admin закрывает
        r = await client.post(f"/appeals/{aid}/close", headers=admin_headers)
        assert r.status_code == 200 and r.json()["status"] == "closed"

        # viewer пишет снова → обращение переоткрывается (open)
        r = await client.post(f"/appeals/{aid}/messages", headers=viewer["headers"], json={"body": "Ещё раз не работает"})
        assert r.status_code == 201 and r.json()["status"] == "open"
    finally:
        await _purge_appeal(aid)


async def test_appeal_foreign_user_denied(client, admin_headers, viewer, ids):
    """Чужое обращение — 404 для другого обычного пользователя; close — только staff (403)."""
    aid = (await client.post("/appeals", headers=viewer["headers"], json={"body": "личный вопрос"})).json()["id"]
    login_name = "ztest_appeal_other"
    async with db.acquire() as conn:
        await conn.execute("delete from users where login=$1", login_name)
        uid = await conn.fetchval(
            "insert into users(organization_id,login,password_hash,is_active,must_change_password) "
            "values($1,$2,$3,true,false) returning id", ids["org"], login_name, hash_password("other12345"))
        role_id = await conn.fetchval("select id from roles where code='user' and organization_id=$1", ids["org"])
        await conn.execute("insert into user_roles(user_id,role_id) values($1,$2)", uid, role_id)
    other_headers = hdr(await login(client, login_name, "other12345"))
    try:
        assert (await client.get(f"/appeals/{aid}", headers=other_headers)).status_code == 404
        r = await client.post(f"/appeals/{aid}/messages", headers=other_headers, json={"body": "чужое"})
        assert r.status_code == 404
        assert (await client.post(f"/appeals/{aid}/close", headers=other_headers)).status_code == 403
        # staff-only списки/статистика недоступны обычному пользователю
        assert (await client.get("/appeals", headers=other_headers)).status_code == 403
        assert (await client.get("/appeals/stats", headers=other_headers)).status_code == 403
    finally:
        await _purge_appeal(aid)
        async with db.acquire() as conn:
            await conn.execute("delete from user_roles where user_id=$1", uid)
            await conn.execute("delete from users where id=$1", uid)


async def test_blocked_account_login_and_appeal(client, admin_headers, ids):
    """Верный пароль + is_active=false → 403 account_blocked (и обращение без
    токена доходит до staff); неверный пароль у того же логина — обычный 401
    (заблокированность не палится тому, кто не знает пароль)."""
    login_name = "ztest_blocked_" + uuid.uuid4().hex[:6]
    async with db.acquire() as conn:
        uid = await conn.fetchval(
            "insert into users(organization_id,login,password_hash,is_active,must_change_password) "
            "values($1,$2,$3,false,false) returning id",
            ids["org"], login_name, hash_password("blockedpw123"))
    try:
        r = await client.post("/auth/login", data={"username": login_name, "password": "blockedpw123"})
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "account_blocked"

        r = await client.post("/auth/login", data={"username": login_name, "password": "wrongpw"})
        assert r.status_code == 401
        assert isinstance(r.json()["detail"], str)  # обычная строка, не code-объект — блокировка не выдана

        r = await client.post("/auth/blocked-appeal", json={"login": login_name, "message": "Разблокируйте, пожалуйста"})
        assert r.status_code == 204

        r = await client.get("/appeals", headers=admin_headers)
        items = [i for i in r.json()["items"] if i["author"] == login_name]
        assert len(items) == 1 and items[0]["subject"] == "Аккаунт заблокирован"

        # аудит: актор — сам заблокированный пользователь (личность установлена по логину)
        async with db.acquire() as conn:
            audit_row = await conn.fetchrow(
                "select actor_user_id from audit_log where entity_type='appeal' and entity_id=$1::uuid and action='create'",
                items[0]["id"])
        assert audit_row is not None and str(audit_row["actor_user_id"]) == str(uid)

        await _purge_appeal(items[0]["id"])

        # несуществующий логин — тоже 204, без утечки (никакого обращения не создаётся)
        r = await client.post("/auth/blocked-appeal", json={"login": "ztest_no_such_user", "message": "x"})
        assert r.status_code == 204
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from login_events where login=$1", login_name)
            await conn.execute("delete from users where id=$1", uid)
