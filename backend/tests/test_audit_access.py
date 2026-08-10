"""Волна B: доступ admin→аудит только по гранту от superadmin (superadmin —
всегда без гранта); единый отчёт активности пользователя; логирование
выгрузок; регрессия на порядок роутов (/audit/access не должен перехватываться
параметризованным /audit/{event_id})."""
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import db, hash_password, hdr, login


async def _superadmin(client):
    return hdr(await login(client, "superadmin", "superadmin"))


@pytest_asyncio.fixture
async def plain_admin(client, ids):
    """Отдельный admin БЕЗ гранта на аудит (не трогаем общий admin_headers,
    чтобы не смешивать состояние с другими тестовыми файлами)."""
    login_name = "ztest_plain_admin"
    async with db.acquire() as conn:
        await conn.execute("delete from audit_access_grants where user_id in (select id from users where login=$1)", login_name)
        await conn.execute("delete from user_roles where user_id in (select id from users where login=$1)", login_name)
        await conn.execute("delete from users where login=$1", login_name)
        uid = await conn.fetchval(
            "insert into users(organization_id,login,password_hash,is_active,must_change_password) "
            "values($1,$2,$3,true,false) returning id", ids["org"], login_name, hash_password("plainadmin123"))
        role_id = await conn.fetchval("select id from roles where code='admin' and organization_id=$1", ids["org"])
        await conn.execute("insert into user_roles(user_id,role_id) values($1,$2)", uid, role_id)
    token = await login(client, login_name, "plainadmin123")
    yield {"id": str(uid), "headers": hdr(token)}
    async with db.acquire() as conn:
        await conn.execute("delete from audit_access_grants where user_id=$1", uid)
        await conn.execute("delete from user_roles where user_id=$1", uid)
        await conn.execute("delete from users where id=$1", uid)


async def test_superadmin_sees_audit_without_grant(client):
    sa = await _superadmin(client)
    r = await client.get("/audit", headers=sa)
    assert r.status_code == 200


async def test_plain_admin_blocked_without_grant(client, plain_admin):
    r = await client.get("/audit", headers=plain_admin["headers"])
    assert r.status_code == 403
    r2 = await client.get("/login-events", headers=plain_admin["headers"])
    assert r2.status_code == 403


async def test_superadmin_grants_and_revokes_admin_access(client, plain_admin):
    sa = await _superadmin(client)
    # выдаём доступ
    r = await client.post(f"/audit/access/{plain_admin['id']}", headers=sa)
    assert r.status_code == 200, r.text
    assert (await client.get("/audit", headers=plain_admin["headers"])).status_code == 200
    assert (await client.get("/login-events", headers=plain_admin["headers"])).status_code == 200
    # список гранта отражает выданный доступ
    granted = await client.get("/audit/access", headers=sa)
    assert any(x["user_id"] == plain_admin["id"] for x in granted.json())
    # отзываем — снова 403
    r = await client.delete(f"/audit/access/{plain_admin['id']}", headers=sa)
    assert r.status_code == 204
    assert (await client.get("/audit", headers=plain_admin["headers"])).status_code == 403


async def test_plain_admin_cannot_manage_grants(client, plain_admin):
    """Управление грантами — только superadmin, не admin (даже с собственным грантом)."""
    r = await client.post(f"/audit/access/{plain_admin['id']}", headers=plain_admin["headers"])
    assert r.status_code == 403


async def test_audit_access_route_not_shadowed_by_event_id(client):
    """Регрессия: /audit/access должен матчиться СВОИМ обработчиком, а не
    параметризованным /audit/{event_id} (порядок регистрации роутов)."""
    sa = await _superadmin(client)
    r = await client.get("/audit/access", headers=sa)
    assert r.status_code == 200
    assert isinstance(r.json(), list)  # список грантов, а не 404 «событие не найдено»


async def test_user_activity_aggregates_logins_events_comments(client, admin_headers, ids, seed_dataset):
    sa = await _superadmin(client)
    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_activity"})).json()["id"]
    try:
        await client.post(f"/dashboards/{did}/comments", headers=admin_headers, json={"body": "активность-тест"})
        r = await client.get(f"/users/{ids['admin']}/activity", headers=sa)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["user"]["login"] == "admin"
        assert data["login_count"] >= 1
        assert any(c["body"] == "активность-тест" for c in data["comments"])
        assert any(e["entity_id"] == did for e in data["events"])
    finally:
        from conftest import purge_dashboard
        await purge_dashboard(did)


async def test_xlsx_export_logged_to_audit(client, admin_headers, ids, seed_dataset):
    sa = await _superadmin(client)
    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_export_log"})).json()["id"]
    try:
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "P"})).json()["id"]
        r = await client.get(f"/dashboard-pages/{pid}/export.xlsx", headers=admin_headers)
        assert r.status_code == 200
        activity = (await client.get(f"/users/{ids['admin']}/activity", headers=sa)).json()
        assert any(e["action"] == "export" and e["entity_id"] == pid for e in activity["events"])
    finally:
        from conftest import purge_dashboard
        await purge_dashboard(did)


async def test_client_export_log_endpoint(client, admin_headers, ids):
    sa = await _superadmin(client)
    r = await client.post("/audit/log-export", headers=admin_headers,
                          json={"entity_type": "dashboard", "entity_id": str(ids["admin"]), "format": "pdf"})
    assert r.status_code == 204
    activity = (await client.get(f"/users/{ids['admin']}/activity", headers=sa)).json()
    assert any(e["action"] == "export" for e in activity["events"])


async def test_login_journal_filters_by_user(client, ids):
    """Журнал входов по одному сотруднику.

    В организации на два десятка учёток общая лента не отвечает на вопрос
    «когда заходил Иванов»: нужен фильтр, и выгрузка должна совпадать с ним.
    """
    sa = await _superadmin(client)
    login_name = "ztest_journal_user"
    async with db.acquire() as conn:
        await conn.execute("delete from login_events where login=$1", login_name)
        await conn.execute("delete from users where login=$1", login_name)
        uid = await conn.fetchval(
            "insert into users(organization_id,login,password_hash,is_active,must_change_password) "
            "values($1,$2,$3,true,false) returning id", ids["org"], login_name, hash_password("journal12345"))
    try:
        await login(client, login_name, "journal12345")          # успешный вход
        await client.post("/auth/login", data={"username": login_name, "password": "wrong"})  # неудачный

        all_events = (await client.get("/login-events", headers=sa)).json()
        assert any(r["login"] != login_name for r in all_events["recent"]), "без фильтра лента общая"
        assert any(s["user_id"] == str(uid) for s in all_events["summary"]), "в сводке есть id для выбора"

        mine = (await client.get(f"/login-events?user_id={uid}", headers=sa)).json()
        assert mine["recent"], "события сотрудника должны быть"
        assert {r["login"] for r in mine["recent"]} == {login_name}
        assert mine["filtered_by_user"] == str(uid)
        # сводка остаётся полной — она же список для выбора в интерфейсе
        assert len(mine["summary"]) == len(all_events["summary"])

        failed = (await client.get(f"/login-events?user_id={uid}&only_failed=true", headers=sa)).json()
        assert failed["recent"] and all(not r["success"] for r in failed["recent"])

        csv = await client.get(f"/login-events/export.csv?user_id={uid}", headers=sa)
        assert csv.status_code == 200
        body = csv.content.decode("utf-8-sig")
        assert login_name in body
        assert "superadmin" not in body, "выгрузка должна повторять фильтр экрана"
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from login_events where user_id=$1 or login=$2", uid, login_name)
            await conn.execute("delete from users where id=$1", uid)


async def test_user_activity_includes_profile_and_appeals(client, admin_headers, ids):
    """Отчёт активности — это «кабинет» сотрудника: роли, отдел, состояние
    учётной записи и обращения, а не только лента событий."""
    sa = await _superadmin(client)
    me = (await client.get("/auth/me", headers=admin_headers)).json()
    data = (await client.get(f"/users/{me['id']}/activity", headers=sa)).json()
    u = data["user"]
    for field in ("roles", "department", "last_login", "must_change_password", "email"):
        assert field in u, f"в карточке нет поля {field}"
    assert isinstance(u["roles"], list) and u["roles"], "роли должны быть заполнены"
    assert "appeals" in data, "обращения — часть кабинета"
