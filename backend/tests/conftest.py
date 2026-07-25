"""Общие фикстуры интеграционных тестов (pytest + httpx против ASGI-приложения).

Подключаемся к БД напрямую (db.connect) и НЕ поднимаем lifespan целиком —
Redis/MinIO не нужны для тестируемых доменов (кэш деградирует мягко). Тестовые
данные создаются с префиксом `t_`/`ztest_` и удаляются в teardown.
"""
import os
import sys

import httpx
import pytest_asyncio
from httpx import ASGITransport

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.auth.bootstrap import ensure_seed  # noqa: E402
from app.modules.auth.security import hash_password  # noqa: E402

BASE = "http://test"


@pytest_asyncio.fixture(scope="session")
async def _seeded():
    """Один раз на сессию: пул БД + гарантированный admin/роли/организация."""
    await db.connect()
    await ensure_seed()
    yield
    await db.disconnect()


@pytest_asyncio.fixture
async def client(_seeded):
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as c:
        yield c


async def purge_dashboard(did):
    """Жёсткое удаление дашборда со всеми FK-детьми (API удаления дашборда нет —
    by design; в тестах чистим напрямую). Порядок — дети раньше родителей."""
    async with db.acquire() as conn:
        rq = "(select id from publication_requests where dashboard_id=$1::uuid)"
        ms = f"(select id from moderation_session where publication_request_id in {rq})"
        await conn.execute(f"delete from revision_transition_log where moderation_session_id in {ms}", did)
        await conn.execute("delete from revision_transition_log where dashboard_version_id in "
                           "(select id from dashboard_versions where dashboard_id=$1::uuid)", did)
        await conn.execute(f"delete from moderation_session where publication_request_id in {rq}", did)
        await conn.execute(f"delete from publication_reviews where publication_request_id in {rq}", did)
        await conn.execute("delete from dashboard_publications where dashboard_id=$1::uuid", did)
        await conn.execute("delete from publication_requests where dashboard_id=$1::uuid", did)
        await conn.execute("delete from widget_versions where widget_id in "
                           "(select id from widgets where dashboard_id=$1::uuid)", did)
        await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
        await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
        await conn.execute("delete from dashboard_versions where dashboard_id=$1::uuid", did)
        await conn.execute("delete from access_grants where dashboard_id=$1::uuid", did)
        await conn.execute("delete from dashboard_favorites where dashboard_id=$1::uuid", did)
        await conn.execute("delete from dashboard_filter_presets where dashboard_id=$1::uuid", did)
        await conn.execute("delete from dashboards where id=$1::uuid", did)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _purge_leftovers(_seeded):
    """Подчистить возможный мусор от прошлых прогонов (ztest_*) до начала сессии."""
    async with db.acquire() as conn:
        dids = [r["id"] for r in await conn.fetch("select id from dashboards where name like 'ztest_%'")]
    for did in dids:
        await purge_dashboard(str(did))
    async with db.acquire() as conn:
        await conn.execute("delete from access_grants where user_id in (select id from users where login like 'ztest_%')")
        await conn.execute("delete from user_roles where user_id in (select id from users where login like 'ztest_%')")
        await conn.execute("update dashboards set published_by=null where published_by in (select id from users where login like 'ztest_%')")
        await conn.execute("delete from users where login like 'ztest_%'")
    yield


async def login(client, username, password):
    r = await client.post("/auth/login", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def hdr(token):
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def admin_headers(client):
    return hdr(await login(client, "admin", "admin"))


@pytest_asyncio.fixture(scope="session")
async def ids(_seeded):
    """Организация и admin по умолчанию."""
    async with db.acquire() as conn:
        org = await conn.fetchval("select id from organizations order by created_at limit 1")
        admin = await conn.fetchval("select id from users where login='admin'")
    return {"org": org, "admin": admin}


@pytest_asyncio.fixture(scope="session")
async def seed_dataset(ids):
    """Минимальный датасет `t_ds`: 2 выпуска (динамика по периодам), строки
    Паспорт/ИНН/СНИЛС × поля plan/fact. Достаточно для всех датасетных виджетов."""
    rows = ["Паспорт", "ИНН", "СНИЛС"]
    plan = [100, 50, 30]
    fact = [90, 55, 28]
    async with db.acquire() as conn:
        await conn.execute("delete from dataset_values where dataset_release_id in "
                           "(select id from dataset_releases where code='t_ds')")
        await conn.execute("delete from dataset_releases where code='t_ds'")
        await conn.execute("delete from objects where name='t_obj' and organization_id=$1", ids["org"])
        # тест-объект (= подразделение) — чтобы работал objects_compare (агрегация по объектам)
        obj = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,'t_obj') returning id", ids["org"])
        rel_old = await conn.fetchval(
            "insert into dataset_releases(organization_id,code,name,status,reporting_period_start,created_by,object_id) "
            "values($1,'t_ds','Тест ДС',$2,'2026-01-01',$3,$4) returning id", ids["org"], "released", ids["admin"], obj)
        rel_new = await conn.fetchval(
            "insert into dataset_releases(organization_id,code,name,status,reporting_period_start,created_by,object_id) "
            "values($1,'t_ds','Тест ДС',$2,'2026-02-01',$3,$4) returning id", ids["org"], "released", ids["admin"], obj)
        for i, r in enumerate(rows):
            # старый выпуск — только plan (для динамики: 2 периода)
            await conn.execute("insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,value_number) "
                               "values($1,$2,$3,'plan',$4)", rel_old, i, r, plan[i] - 5)
            # новый (активный) выпуск — plan+fact (для kpi/plan_fact/compare/heatmap/table)
            await conn.execute("insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,value_number) "
                               "values($1,$2,$3,'plan',$4)", rel_new, i, r, plan[i])
            await conn.execute("insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,value_number) "
                               "values($1,$2,$3,'fact',$4)", rel_new, i, r, fact[i])
    yield {"code": "t_ds", "rows": rows, "plan": plan, "fact": fact, "plan_sum": sum(plan)}
    async with db.acquire() as conn:
        await conn.execute("delete from dataset_values where dataset_release_id in "
                           "(select id from dataset_releases where code='t_ds')")
        await conn.execute("delete from dataset_releases where code='t_ds'")
        await conn.execute("delete from objects where name='t_obj' and organization_id=$1", ids["org"])


@pytest_asyncio.fixture
async def viewer(client, ids):
    """Непривилегированный пользователь (роль `user`) + его токен. Чистится после теста."""
    login_name = "ztest_viewer"
    async with db.acquire() as conn:
        await conn.execute("delete from access_grants where user_id in (select id from users where login=$1)", login_name)
        await conn.execute("delete from user_roles where user_id in (select id from users where login=$1)", login_name)
        await conn.execute("delete from users where login=$1", login_name)
        uid = await conn.fetchval(
            "insert into users(organization_id,login,password_hash,is_active,must_change_password) "
            "values($1,$2,$3,true,false) returning id", ids["org"], login_name, hash_password("viewer123"))
        role_id = await conn.fetchval("select id from roles where code='user' and organization_id=$1", ids["org"])
        await conn.execute("insert into user_roles(user_id,role_id) values($1,$2)", uid, role_id)
    token = await login(client, login_name, "viewer123")
    yield {"id": str(uid), "headers": hdr(token)}
    async with db.acquire() as conn:
        await conn.execute("delete from access_grants where user_id=$1", uid)
        await conn.execute("delete from user_roles where user_id=$1", uid)
        await conn.execute("delete from users where id=$1", uid)


@pytest_asyncio.fixture
async def moderator_user(client, ids):
    """Отдельный модератор (роль `moderator`) — чтобы одобрять чужие дашборды
    (свой одобрять нельзя: разделение обязанностей). Чистится после теста."""
    login_name = "ztest_moder"
    async with db.acquire() as conn:
        await conn.execute("delete from user_roles where user_id in (select id from users where login=$1)", login_name)
        await conn.execute("delete from users where login=$1", login_name)
        uid = await conn.fetchval(
            "insert into users(organization_id,login,password_hash,is_active,must_change_password) "
            "values($1,$2,$3,true,false) returning id", ids["org"], login_name, hash_password("moder123"))
        role_id = await conn.fetchval("select id from roles where code='moderator' and organization_id=$1", ids["org"])
        await conn.execute("insert into user_roles(user_id,role_id) values($1,$2)", uid, role_id)
    token = await login(client, login_name, "moder123")
    yield {"id": str(uid), "headers": hdr(token)}
    async with db.acquire() as conn:
        await conn.execute("delete from user_roles where user_id=$1", uid)
        await conn.execute("delete from users where id=$1", uid)
