"""Удаление дашборда: стоп-факторы, каскад и права.

Раньше удаления дашборда не существовало вовсе (страницу, виджет, грант,
комментарий, слепок архива удалить можно было, а сам дашборд — нет). Здесь
фиксируем правила: не удаляем то, что «в работе» (опубликован, на проверке,
входит в витрину), удаляет ТОЛЬКО суперадминистратор (сужено 11.08.2026 —
раньше мог админ и модератор-автор), слепки архива переживают удаление,
а висячих строк контура доступа не остаётся.
"""
import pytest

from app import db

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _mk(client, headers, name):
    return (await client.post("/dashboards", headers=headers, json={"name": name})).json()["id"]


async def test_delete_dashboard_removes_children(client, admin_headers, superadmin_headers):
    did = await _mk(client, admin_headers, "ztest_dd_full")
    page = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                              json={"name": "ztest_dd_page"})).json()
    await client.post(f"/dashboard-pages/{page['id']}/widgets", headers=admin_headers,
                      json={"name": "ztest_dd_w", "widget_type": "kpi", "config": {"value": 1}})

    r = await client.delete(f"/dashboards/{did}", headers=superadmin_headers)
    assert r.status_code == 204, r.text
    assert (await client.get(f"/dashboards/{did}", headers=admin_headers)).status_code == 404
    assert (await client.delete(f"/dashboards/{did}", headers=superadmin_headers)).status_code == 404

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


async def test_delete_blocked_while_published_or_on_review(client, admin_headers, superadmin_headers):
    did = await _mk(client, admin_headers, "ztest_dd_pub")
    try:
        await client.post(f"/dashboards/{did}/publish", headers=admin_headers)
        r = await client.delete(f"/dashboards/{did}", headers=superadmin_headers)
        assert r.status_code == 409 and "снимите его с публикации" in r.json()["detail"]

        await client.post(f"/dashboards/{did}/unpublish", headers=admin_headers)
        await client.post(f"/dashboards/{did}/submit-review", headers=admin_headers)
        r = await client.delete(f"/dashboards/{did}", headers=superadmin_headers)
        assert r.status_code == 409 and "отзовите заявку" in r.json()["detail"]

        await client.post(f"/dashboards/{did}/cancel-review", headers=admin_headers)
        assert (await client.delete(f"/dashboards/{did}", headers=superadmin_headers)).status_code == 204
    except Exception:
        from conftest import purge_dashboard
        await purge_dashboard(did)
        raise


async def test_delete_blocked_while_in_showcase(client, admin_headers, superadmin_headers):
    did = await _mk(client, admin_headers, "ztest_dd_show")
    sc = (await client.post("/showcases", headers=admin_headers, json={"name": "ztest_dd_sc"})).json()
    try:
        await client.post(f"/showcases/{sc['id']}/items", headers=admin_headers,
                          json={"dashboard_id": did})
        r = await client.delete(f"/dashboards/{did}", headers=superadmin_headers)
        assert r.status_code == 409
        assert "ztest_dd_sc" in r.json()["detail"]
    finally:
        await client.delete(f"/showcases/{sc['id']}", headers=admin_headers)
        from conftest import purge_dashboard
        await purge_dashboard(did)


async def test_delete_only_for_superadmin(client, admin_headers, moderator_user, viewer, superadmin_headers):
    """Удаление сузили до суперадминистратора (решение заказчика 11.08.2026):
    ни зритель, ни модератор, ни ДАЖЕ администратор дашборд не удаляют —
    им остаются обратимые действия (снять с публикации, в архив)."""
    did = await _mk(client, admin_headers, "ztest_dd_perm")
    try:
        for who, headers in (("зритель", viewer["headers"]),
                             ("модератор", moderator_user["headers"]),
                             ("администратор", admin_headers)):
            r = await client.delete(f"/dashboards/{did}", headers=headers)
            assert r.status_code == 403, f"{who} не должен удалять дашборд: {r.text}"
        async with db.acquire() as conn:
            assert await conn.fetchval("select count(*) from dashboards where id=$1::uuid", did) == 1

        # а суперадминистратор — удаляет
        assert (await client.delete(f"/dashboards/{did}", headers=superadmin_headers)).status_code == 204
    finally:
        from conftest import purge_dashboard
        await purge_dashboard(did)


async def test_moderator_cannot_delete_own_dashboard(client, moderator_user):
    """Раньше модератор удалял СВОЙ дашборд — теперь нет: удаление необратимо."""
    did = await _mk(client, moderator_user["headers"], "ztest_dd_own")
    try:
        r = await client.delete(f"/dashboards/{did}", headers=moderator_user["headers"])
        assert r.status_code == 403, r.text
    finally:
        from conftest import purge_dashboard
        await purge_dashboard(did)
