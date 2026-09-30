"""Строки прав уходят вместе со своим объектом (миграция 058, 30.09.2026).

Строку `securable_objects` заводит триггер при создании папки, дашборда и
виджета, а при удалении её не убирал никто — к 30.09 на дев-стенде из 102 225
строк живым объектам соответствовали 78. Теперь их убирает триггер на
удалении; живых детей удалённого родителя он отцепляет, а не уносит каскадом.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import db, purge_dashboard  # noqa: E402


async def _rows(conn, kind, oid):
    return await conn.fetchval(
        "select count(*) from securable_objects where object_type=$1::securable_type and object_id=$2::uuid", kind, oid)


async def test_widget_and_dashboard_rows_go_with_them(client, admin_headers):
    """Удалили виджет — его строки нет; удалили дашборд — нет и его."""
    did = (await client.post("/dashboards", headers=admin_headers,
                             json={"name": "ztest_sec_dash", "force": True})).json()["id"]
    try:
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                                 json={"name": "P"})).json()["id"]
        wids = []
        for i in range(2):
            r = await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                                  json={"name": f"t{i}", "widget_type": "text", "config": {"text": "x"}})
            assert r.status_code == 201, r.text
            wids.append(r.json()["id"])
        async with db.acquire() as conn:
            assert await _rows(conn, "dashboard", did) == 1
            assert await _rows(conn, "widget", wids[0]) == 1, "строку заводит триггер создания"

        r = await client.delete(f"/widgets/{wids[0]}", headers=admin_headers)
        assert r.status_code == 204, r.text
        async with db.acquire() as conn:
            assert await _rows(conn, "widget", wids[0]) == 0, "удалённый виджет не оставляет строки прав"
            assert await _rows(conn, "widget", wids[1]) == 1, "соседний виджет не задет"
    finally:
        await purge_dashboard(did)
    async with db.acquire() as conn:
        assert await _rows(conn, "dashboard", did) == 0
        assert await _rows(conn, "widget", wids[1]) == 0, "виджеты уходят вместе с дашбордом"


async def test_surviving_child_is_detached_not_cascaded(client, admin_headers, ids):
    """🔴 Удалили папку — дашборд в ней остаётся, и его строка прав тоже.

    Внешний ключ parent_securable_id объявлен ON DELETE CASCADE: без
    отцепления удаление строки папки снесло бы строку живого дашборда.
    """
    async with db.acquire() as conn:
        oid = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,'ztest_sec_obj') returning id", ids["org"])
        fid = await conn.fetchval(
            "insert into folders(organization_id,object_id,name) values($1,$2,'ztest_sec_folder') returning id",
            ids["org"], oid)
    did = (await client.post("/dashboards", headers=admin_headers,
                             json={"name": "ztest_sec_in_folder", "force": True})).json()["id"]
    try:
        async with db.acquire() as conn:
            # Дашборд, созданный сразу в папке: строка прав с родителем-папкой.
            await conn.execute("delete from securable_objects where object_type='dashboard' "
                               "and object_id=$1::uuid", did)
            await conn.execute(
                "insert into securable_objects(organization_id, object_type, object_id, parent_securable_id, "
                "inherit_permissions) select $1, 'dashboard', $2::uuid, id, true from securable_objects "
                "where object_type='folder' and object_id=$3", ids["org"], did, fid)
            await conn.execute("update dashboards set folder_id=$2 where id=$1::uuid", did, fid)

            await conn.execute("delete from folders where id=$1", fid)
            assert await _rows(conn, "folder", str(fid)) == 0
            row = await conn.fetchrow(
                "select parent_securable_id from securable_objects where object_type='dashboard' "
                "and object_id=$1::uuid", did)
            assert row is not None, "строка живого дашборда не должна уйти каскадом от папки"
            assert row["parent_securable_id"] is None, "а отцепиться от удалённой папки — должна"
    finally:
        await purge_dashboard(did)
        async with db.acquire() as conn:
            await conn.execute("delete from objects where id=$1", oid)
