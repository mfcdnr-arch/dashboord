"""Удаление дашборда: стоп-факторы, каскад и права.

Раньше удаления дашборда не существовало вовсе (страницу, виджет, грант,
комментарий, слепок архива удалить можно было, а сам дашборд — нет). Здесь
фиксируем правила: не удаляем то, что «в работе» (опубликован, на проверке,
входит в витрину), чужое удаляет только админ, слепки архива переживают
удаление, а висячих строк контура доступа не остаётся.
"""
import pytest

from app import db

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _mk(client, headers, name):
    return (await client.post("/dashboards", headers=headers, json={"name": name})).json()["id"]


async def test_delete_dashboard_removes_children(client, admin_headers):
    did = await _mk(client, admin_headers, "ztest_dd_full")
    page = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                              json={"name": "ztest_dd_page"})).json()
    await client.post(f"/dashboard-pages/{page['id']}/widgets", headers=admin_headers,
                      json={"name": "ztest_dd_w", "widget_type": "kpi", "config": {"value": 1}})

    r = await client.delete(f"/dashboards/{did}", headers=admin_headers)
    assert r.status_code == 204, r.text
    assert (await client.get(f"/dashboards/{did}", headers=admin_headers)).status_code == 404
    assert (await client.delete(f"/dashboards/{did}", headers=admin_headers)).status_code == 404

    async with db.acquire() as conn:
        for table in ("dashboard_pages", "widgets", "dashboard_versions", "access_grants"):
            left = await conn.fetchval(
                f"select count(*) from {table} where dashboard_id=$1::uuid", did)
            assert left == 0, table
        # контур доступа не оставил висячих строк
        assert await conn.fetchval(
            "select count(*) from securable_objects where object_type='dashboard' and object_id=$1::uuid",
            did) == 0
        # удаление зафиксировано триггером аудита (ровно одна запись, без дубля)
        assert await conn.fetchval(
            "select count(*) from audit_log where entity_type='dashboard' and entity_id=$1::uuid "
            "and action='delete'", did) == 1


async def test_delete_blocked_while_published_or_on_review(client, admin_headers):
    did = await _mk(client, admin_headers, "ztest_dd_pub")
    try:
        await client.post(f"/dashboards/{did}/publish", headers=admin_headers)
        r = await client.delete(f"/dashboards/{did}", headers=admin_headers)
        assert r.status_code == 409 and "снимите его с публикации" in r.json()["detail"]

        await client.post(f"/dashboards/{did}/unpublish", headers=admin_headers)
        await client.post(f"/dashboards/{did}/submit-review", headers=admin_headers)
        r = await client.delete(f"/dashboards/{did}", headers=admin_headers)
        assert r.status_code == 409 and "отзовите заявку" in r.json()["detail"]

        await client.post(f"/dashboards/{did}/cancel-review", headers=admin_headers)
        assert (await client.delete(f"/dashboards/{did}", headers=admin_headers)).status_code == 204
    except Exception:
        from conftest import purge_dashboard
        await purge_dashboard(did)
        raise


async def test_delete_blocked_while_in_showcase(client, admin_headers):
    did = await _mk(client, admin_headers, "ztest_dd_show")
    sc = (await client.post("/showcases", headers=admin_headers, json={"name": "ztest_dd_sc"})).json()
    try:
        await client.post(f"/showcases/{sc['id']}/items", headers=admin_headers,
                          json={"dashboard_id": did})
        r = await client.delete(f"/dashboards/{did}", headers=admin_headers)
        assert r.status_code == 409
        assert "ztest_dd_sc" in r.json()["detail"]
    finally:
        await client.delete(f"/showcases/{sc['id']}", headers=admin_headers)
        from conftest import purge_dashboard
        await purge_dashboard(did)


async def test_delete_requires_role(client, admin_headers, viewer):
    did = await _mk(client, admin_headers, "ztest_dd_perm")
    try:
        assert (await client.delete(f"/dashboards/{did}", headers=viewer["headers"])).status_code == 403
        async with db.acquire() as conn:
            assert await conn.fetchval("select count(*) from dashboards where id=$1::uuid", did) == 1
    finally:
        from conftest import purge_dashboard
        await purge_dashboard(did)
