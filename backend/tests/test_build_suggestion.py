"""Предложение собрать дашборд: данные есть, а дашборда на них нет.

Данные копятся сами (файл в папку → распознавание → выпуск), а дашборда может
не быть месяцами: человек не всегда знает, что система уже готова его собрать.
Предложение должно исчезать, как только дашборд появился, — иначе оно
превратится в фоновый шум, который перестают замечать.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

import pytest_asyncio

from app import db


@pytest_asyncio.fixture
async def obj_with_data(client, admin_headers, ids):
    r = await client.post("/objects", headers=admin_headers, json={"name": "ztest_sugg_obj"})
    oid = r.json()["id"]
    r = await client.post(f"/objects/{oid}/folders", headers=admin_headers, json={"name": "ztest_sugg_folder"})
    fid = r.json()["id"]
    async with db.acquire() as conn:
        uid = await conn.fetchval("select id from users where login='admin'")
        for period in ("2026-07-15", "2026-07-22", "2026-07-29"):
            await conn.execute(
                "insert into dataset_releases(organization_id, object_id, code, name, status, "
                "reporting_period_start, created_by) "
                "values($1,$2::uuid,'ztest_sugg_ds','Форма','validated',$3::text::date,$4)",
                ids["org"], oid, period, uid)
    yield {"object_id": oid, "folder_id": fid}
    async with db.acquire() as conn:
        await conn.execute("delete from dataset_releases where object_id=$1::uuid", oid)
        await conn.execute("delete from folders where id=$1::uuid", fid)
        await conn.execute("delete from objects where id=$1::uuid", oid)


async def test_suggests_when_data_has_no_dashboard(client, admin_headers, obj_with_data):
    r = await client.get(f"/objects/{obj_with_data['object_id']}/build-suggestion", headers=admin_headers)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["suggest"] is True, s
    assert s["periods"] == 3 and s["releases"] == 3
    assert s["first_period"] == "2026-07-15" and s["last_period"] == "2026-07-29"


async def test_no_suggestion_without_data(client, admin_headers):
    r = await client.post("/objects", headers=admin_headers, json={"name": "ztest_sugg_empty"})
    oid = r.json()["id"]
    try:
        r = await client.get(f"/objects/{oid}/build-suggestion", headers=admin_headers)
        assert r.json()["suggest"] is False
        assert r.json()["reason"] == "no_data", "пустому объекту предлагать нечего"
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from objects where id=$1::uuid", oid)


async def test_suggestion_disappears_when_dashboard_exists(client, admin_headers, obj_with_data):
    """Дашборд в папке объекта — предложение снимается."""
    fid = obj_with_data["folder_id"]
    r = await client.post("/dashboards", headers=admin_headers,
                          json={"name": "ztest_sugg_dash", "folder_id": fid})
    did = r.json()["id"]
    try:
        r = await client.get(f"/objects/{obj_with_data['object_id']}/build-suggestion", headers=admin_headers)
        assert r.json()["suggest"] is False, r.json()
        assert r.json()["reason"] == "has_dashboard"
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)


async def test_dashboard_found_by_widget_even_without_folder(client, admin_headers, obj_with_data):
    """Дашборд без папки, но с виджетом на данные объекта, — тоже считается.

    Одного признака мало: дашборд могли собрать до автопривязки папок или
    перенести в другую папку, и предложение звало бы собирать второй такой же.
    """
    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_sugg_dash2"})
    did = r.json()["id"]
    r = await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "Стр"})
    pid = r.json()["id"]
    try:
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "Показатель", "widget_type": "kpi",
            "config": {"dataset_code": "ztest_sugg_ds", "value_field": "obr"}})

        r = await client.get(f"/objects/{obj_with_data['object_id']}/build-suggestion", headers=admin_headers)
        assert r.json()["suggest"] is False, r.json()
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
            await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)


async def test_suggestion_is_staff_only(client, viewer, obj_with_data):
    r = await client.get(f"/objects/{obj_with_data['object_id']}/build-suggestion",
                         headers=viewer["headers"])
    assert r.status_code == 403
