"""Операции с учётными записями попадают в журнал действий (20.09.2026).

До этой правки `select count(*) from audit_log where entity_type='user'`
давал 0 при сотнях тысяч событий по другим сущностям: `write_event` в
users/service.py не вызывался ни разу, а триггера на таблице `users` — в
отличие от dashboards/widgets/object_acl — нет. Сброс чужого пароля, выдача
роли admin, блокировка и удаление не оставляли следа. В госсистеме это
первое, о чём спрашивают при разборе спорной ситуации.

Проверяется СОДЕРЖИМОЕ записи, а не факт её появления: журнал, в котором не
видно, какую роль выдали и кому, на вопрос «кто это сделал» не отвечает.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db

LOGIN = "ztest_audit_user"


async def _events(conn, uid, action=None):
    q = ("select action, old_data, new_data, actor_user_id from audit_log "
         "where entity_type='user' and entity_id=$1::uuid")
    args = [uid]
    if action:
        q += " and action=$2::audit_action"
        args.append(action)
    return await conn.fetch(q + " order by created_at", *args)


async def _cleanup(uid=None):
    async with db.acquire() as conn:
        if uid:
            await conn.execute("delete from audit_log where entity_type='user' and entity_id=$1::uuid", uid)
        await conn.execute("delete from user_roles where user_id in (select id from users where login=$1)", LOGIN)
        await conn.execute("delete from users where login=$1", LOGIN)


async def test_user_lifecycle_is_logged(client, admin_headers, ids):
    """Заведение, выдача роли, блокировка и сброс пароля видны в журнале."""
    await _cleanup()
    async with db.acquire() as conn:
        roles = {r["code"]: str(r["id"]) for r in await conn.fetch(
            "select id, code from roles where organization_id=$1", ids["org"])}

    created = await client.post("/users", headers=admin_headers, json={
        "login": LOGIN, "password": "Ztest#2026ab", "last_name": "Тестов",
        "role_ids": [roles["user"]]})
    assert created.status_code in (200, 201), created.text
    uid = created.json()["id"]
    try:
        async with db.acquire() as conn:
            ev = await _events(conn, uid, "create")
            assert len(ev) == 1, "заведение учётной записи не попало в журнал"
            assert ev[0]["actor_user_id"] is not None, "в журнале не видно, КТО завёл учётку"
            import json as js
            assert "user" in js.loads(ev[0]["new_data"])["roles"]

        # Выдача роли admin — самое чувствительное действие.
        r = await client.patch(f"/users/{uid}", headers=admin_headers,
                               json={"role_ids": [roles["user"], roles["admin"]]})
        assert r.status_code == 200, r.text
        async with db.acquire() as conn:
            ev = await _events(conn, uid, "update")
            import json as js
            new = js.loads(ev[-1]["new_data"])
            old = js.loads(ev[-1]["old_data"])
            assert "admin" in new["roles"], "выдача роли admin не видна в журнале"
            assert "admin" not in old["roles"], "в журнале не видно, что роли ИЗМЕНИЛИСЬ"

        # Блокировка.
        r = await client.post(f"/users/{uid}/active", headers=admin_headers, json={"is_active": False})
        assert r.status_code == 200, r.text
        async with db.acquire() as conn:
            import json as js
            ev = await _events(conn, uid, "update")
            assert js.loads(ev[-1]["new_data"])["is_active"] is False, "блокировка не видна в журнале"

        # Сброс чужого пароля — и НИ ОДНОГО следа самого пароля.
        r = await client.post(f"/users/{uid}/reset-password", headers=admin_headers,
                              json={"password": "Ztest#2026cd"})
        assert r.status_code == 200, r.text
        async with db.acquire() as conn:
            import json as js
            ev = await _events(conn, uid, "update")
            last = js.loads(ev[-1]["new_data"])
            assert last["password_reset"] is True, "сброс пароля не попал в журнал"
            dump = (ev[-1]["new_data"] or "") + (ev[-1]["old_data"] or "")
            assert "Ztest#2026cd" not in dump, "🔴 пароль утёк в журнал действий"
            assert "$2b$" not in dump and "$2a$" not in dump, "🔴 хеш пароля утёк в журнал"
    finally:
        await _cleanup(uid)


async def test_deletion_is_logged_and_names_the_user(client, admin_headers, ids):
    """Удаление оставляет след с именем — иначе в журнале голый идентификатор."""
    await _cleanup()
    async with db.acquire() as conn:
        role = str(await conn.fetchval(
            "select id from roles where organization_id=$1 and code='user'", ids["org"]))
    created = await client.post("/users", headers=admin_headers, json={
        "login": LOGIN, "password": "Ztest#2026ab", "last_name": "Удаляемый", "role_ids": [role]})
    uid = created.json()["id"]
    try:
        r = await client.delete(f"/users/{uid}", headers=admin_headers)
        assert r.status_code in (200, 204), r.text
        async with db.acquire() as conn:
            import json as js
            ev = await _events(conn, uid, "delete")
            assert len(ev) == 1, "удаление учётной записи не попало в журнал"
            assert js.loads(ev[0]["old_data"])["login"] == LOGIN, \
                "в журнале не видно, ЧЬЮ учётку удалили"
    finally:
        await _cleanup(uid)


async def test_audit_filter_knows_the_new_entity(client, admin_headers):
    """Сущность подписана по-человечески — иначе в фильтре журнала «user»."""
    from app.modules.audit.service import ENTITY_LABELS
    assert ENTITY_LABELS.get("user") == "Учётная запись"
    assert ENTITY_LABELS.get("department") == "Отдел"


async def test_partial_patch_keeps_untouched_fields(client, admin_headers, ids):
    """🔴 Частичная правка не стирает ФИО, почту и отдел.

    Найдено 20.09.2026 по журналу действий, как только он начал писать
    «было/стало»: выдача роли превращала «Проверкин» в пустое имя. Через
    форму не проявлялось (она шлёт полный набор), но PATCH по определению
    частичный, и первый вызов мимо формы терял данные молча."""
    await _cleanup()
    async with db.acquire() as conn:
        roles = {r["code"]: str(r["id"]) for r in await conn.fetch(
            "select id, code from roles where organization_id=$1", ids["org"])}
    created = await client.post("/users", headers=admin_headers, json={
        "login": LOGIN, "password": "Ztest#2026ab", "last_name": "Фамилия",
        "first_name": "Имя", "middle_name": "Отчество", "email": "ztest@example.org",
        "role_ids": [roles["user"]]})
    uid = created.json()["id"]
    try:
        # Присылаем ТОЛЬКО роли.
        r = await client.patch(f"/users/{uid}", headers=admin_headers,
                               json={"role_ids": [roles["user"], roles["admin"]]})
        assert r.status_code == 200, r.text
        async with db.acquire() as conn:
            row = await conn.fetchrow(
                "select full_name, last_name, email from users where id=$1::uuid", uid)
        assert row["full_name"] == "Фамилия Имя Отчество", \
            f"правка ролей стёрла ФИО: {row['full_name']!r}"
        assert row["email"] == "ztest@example.org", "правка ролей стёрла почту"

        # Меняем ТОЛЬКО фамилию — имя и отчество должны уцелеть.
        r = await client.patch(f"/users/{uid}", headers=admin_headers,
                               json={"last_name": "Новая"})
        assert r.status_code == 200, r.text
        async with db.acquire() as conn:
            row = await conn.fetchrow("select full_name from users where id=$1::uuid", uid)
        assert row["full_name"] == "Новая Имя Отчество", \
            f"правка фамилии потеряла имя/отчество: {row['full_name']!r}"

        # Явный null — это «стереть»: через форму так очищают поле.
        r = await client.patch(f"/users/{uid}", headers=admin_headers, json={"email": None})
        assert r.status_code == 200, r.text
        async with db.acquire() as conn:
            assert await conn.fetchval(
                "select email from users where id=$1::uuid", uid) is None, \
                "явный null перестал стирать значение — очистить поле через форму нельзя"
    finally:
        await _cleanup(uid)
