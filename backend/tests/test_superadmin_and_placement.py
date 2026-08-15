"""Superadmin как верхняя роль + умное размещение показателя на дашборде.

(1) Носитель ОДНОЙ роли superadmin должен уметь всё, что умеет admin: право
выдавалось модулями через `require_roles("admin", "moderator")`, и верхняя роль
иерархии молча оказывалась слабее — на загрузке документов, разметке и выпуске
она получала 403. На стенде это не всплывало, потому что у учётки заказчика
есть и роль admin.

(2) Карточка нового показателя должна вставать РЯДОМ с виджетом, который
показывает те же данные: добавленная «в конец» она уезжает вниз и теряется.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

import pytest_asyncio

from app import db
from app.modules.auth.security import hash_password


@pytest_asyncio.fixture
async def pure_superadmin(client, ids):
    """Учётка ТОЛЬКО с ролью superadmin — без admin и moderator."""
    from tests.conftest import hdr, login
    login_name = "ztest_pure_super"
    async with db.acquire() as conn:
        await conn.execute("delete from user_roles where user_id in (select id from users where login=$1)", login_name)
        await conn.execute("delete from users where login=$1", login_name)
        uid = await conn.fetchval(
            "insert into users(organization_id,login,password_hash,is_active,must_change_password) "
            "values($1,$2,$3,true,false) returning id", ids["org"], login_name, hash_password("super123"))
        role_id = await conn.fetchval(
            "select id from roles where code='superadmin' and organization_id=$1", ids["org"])
        await conn.execute("insert into user_roles(user_id,role_id) values($1,$2)", uid, role_id)
    token = await login(client, login_name, "super123")
    yield {"id": str(uid), "headers": hdr(token)}
    async with db.acquire() as conn:
        await conn.execute("delete from user_roles where user_id=$1", uid)
        await conn.execute("delete from users where id=$1", uid)


async def test_superadmin_alone_can_manage_objects_and_data(client, pure_superadmin):
    """Верхняя роль не может уметь меньше admin: объекты, папки, документы."""
    h = pure_superadmin["headers"]
    r = await client.post("/objects", headers=h, json={"name": "ztest_super_obj"})
    assert r.status_code == 201, r.text
    oid = r.json()["id"]
    try:
        r = await client.post(f"/objects/{oid}/folders", headers=h, json={"name": "ztest_super_folder"})
        assert r.status_code == 201, r.text
        fid = r.json()["id"]

        # Списки документов и справочники тоже должны открываться.
        assert (await client.get(f"/folders/{fid}/documents", headers=h)).status_code == 200
        assert (await client.get("/services", headers=h)).status_code in (200, 404)
        # Витрины и очередь модерации — admin-функции, верхняя роль их видит.
        assert (await client.get("/showcases", headers=h)).status_code == 200
        assert (await client.get("/moderation/queue", headers=h)).status_code == 200

        async with db.acquire() as conn:
            await conn.execute("delete from securable_objects where object_type='folder' and object_id=$1::uuid", fid)
            await conn.execute("delete from folders where id=$1::uuid", fid)
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from folders where object_id=$1::uuid", oid)
            await conn.execute("delete from objects where id=$1::uuid", oid)


async def test_superadmin_alone_sees_and_manages_dashboards(client, pure_superadmin, admin_headers):
    """Чужой дашборд виден верхней роли: без этого она не смогла бы его удалить."""
    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_super_vis"})
    did = r.json()["id"]
    try:
        r = await client.get("/dashboards?limit=200", headers=pure_superadmin["headers"])
        assert any(d["id"] == did for d in r.json()["items"]), "superadmin должен видеть чужие дашборды"
        assert (await client.get(f"/dashboards/{did}", headers=pure_superadmin["headers"])).status_code == 200
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)


async def test_metric_card_lands_next_to_related_widget(client, admin_headers, seed_dataset):
    """Карточка показателя встаёт рядом с виджетом, показывающим те же поля."""
    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_place_dash"})
    did = r.json()["id"]
    r = await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "Обзор"})
    pid = r.json()["id"]
    try:
        # Общий график, перечисляющий ВСЕ поля: он не должен выигрывать у
        # карточки нужного показателя — иначе новая карточка уезжает под него
        # в самый низ страницы (реальный случай на дашборде заказчика).
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "Сравнение всех", "widget_type": "compare", "width": 12, "height": 8,
            "position_x": 0, "position_y": 20,
            "config": {"dataset_code": seed_dataset["code"], "value_fields": ["plan", "fact"]}})
        # Родственник: показывает поле plan. И «чужой» виджет — по другому полю.
        rel = await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "План", "widget_type": "kpi", "width": 3, "height": 3,
            "position_x": 0, "position_y": 0,
            "config": {"dataset_code": seed_dataset["code"], "value_field": "plan"}})
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "Факт", "widget_type": "kpi", "width": 3, "height": 3,
            "position_x": 0, "position_y": 6,
            "config": {"dataset_code": seed_dataset["code"], "value_field": "fact"}})

        r = await client.post("/dashboards/place-metric", headers=admin_headers, json={
            "page_id": pid, "metric_code": "ztest_place_metric", "name": "Доля плана, %",
            "unit": "%", "based_on": ["plan"], "dataset_code": seed_dataset["code"]})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["placed_near"] == rel.json()["id"], "рядом должен встать именно родственник по полю"
        # Справа в том же ряду: место есть (3 + 3 ≤ 12).
        assert body["position"]["position_y"] == 0 and body["position"]["position_x"] == 3, body

        async with db.acquire() as conn:
            cfg = await conn.fetchval(
                "select config::text from widgets where id=$1::uuid", body["widget_id"])
        assert "ztest_place_metric" in cfg
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
            await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)


async def test_metric_card_falls_back_when_no_relative(client, admin_headers, seed_dataset):
    """Родственника нет — карточка просто уходит в конец страницы, без ошибки."""
    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_place_empty"})
    did = r.json()["id"]
    r = await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "Пусто"})
    pid = r.json()["id"]
    try:
        r = await client.post("/dashboards/place-metric", headers=admin_headers, json={
            "page_id": pid, "metric_code": "ztest_place_alone", "name": "Одинокий показатель",
            "based_on": ["nothing"], "dataset_code": "no_such_ds"})
        assert r.status_code == 201, r.text
        assert r.json()["placed_near"] is None
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
            await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)
