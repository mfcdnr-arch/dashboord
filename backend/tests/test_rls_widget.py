"""RLS widget-level (миграция 004, п.3–4): whitelist виджетов внутри видимого
дашборда. Как только на дашборде появляется хотя бы один widget-грант, зритель-
по-гранту видит ТОЛЬКО выданные ему виджеты; привилегированные и автор — все.
Регрессия здесь = утечка доступа к отдельным показателям, критично для госсистемы."""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import purge_dashboard


async def test_widget_whitelist_flow(client, admin_headers, viewer, seed_dataset):
    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_wrls"})
    did = r.json()["id"]
    try:
        r = await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "P"})
        pid = r.json()["id"]
        wa = (await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
              json={"name": "A", "widget_type": "kpi", "config": {"dataset_code": "t_ds", "value_field": "plan"}})).json()["id"]
        wb = (await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
              json={"name": "B", "widget_type": "table", "config": {"dataset_code": "t_ds"}})).json()["id"]

        # дашборд-грант + публикация: viewer видит дашборд и ОБА виджета (whitelist не активен)
        await client.post(f"/dashboards/{did}/grants", headers=admin_headers,
                          json={"grantee_type": "user", "user_id": viewer["id"]})
        await client.post(f"/dashboards/{did}/publish", headers=admin_headers)

        r = await client.get(f"/dashboard-pages/{pid}/data", headers=viewer["headers"])
        assert r.status_code == 200
        assert {w["id"] for w in r.json()["widgets"]} == {wa, wb}
        assert (await client.get(f"/widgets/{wa}/data", headers=viewer["headers"])).status_code == 200
        assert (await client.get(f"/widgets/{wb}/data", headers=viewer["headers"])).status_code == 200

        # выдаём widget-грант ТОЛЬКО на A → whitelist активируется
        r = await client.post(f"/dashboards/{did}/grants", headers=admin_headers,
                              json={"grantee_type": "user", "user_id": viewer["id"], "scope": "widget", "widget_id": wa})
        assert r.status_code in (200, 201), r.text
        wgrant = r.json()["id"]

        # viewer теперь видит только A: батч, список виджетов, единичные данные, drill
        r = await client.get(f"/dashboard-pages/{pid}/data", headers=viewer["headers"])
        assert {w["id"] for w in r.json()["widgets"]} == {wa}
        r = await client.get(f"/dashboard-pages/{pid}/widgets", headers=viewer["headers"])
        assert {w["id"] for w in r.json()["widgets"]} == {wa}
        assert (await client.get(f"/widgets/{wa}/data", headers=viewer["headers"])).status_code == 200
        assert (await client.get(f"/widgets/{wb}/data", headers=viewer["headers"])).status_code == 404
        assert (await client.get(f"/widgets/{wb}/drill", headers=viewer["headers"])).status_code == 404

        # админ (привилегированный) по-прежнему видит оба
        r = await client.get(f"/dashboard-pages/{pid}/data", headers=admin_headers)
        assert {w["id"] for w in r.json()["widgets"]} == {wa, wb}

        # снимаем widget-грант → whitelist выключается, viewer снова видит оба
        assert (await client.delete(f"/dashboards/{did}/grants/{wgrant}", headers=admin_headers)).status_code == 204
        r = await client.get(f"/dashboard-pages/{pid}/data", headers=viewer["headers"])
        assert {w["id"] for w in r.json()["widgets"]} == {wa, wb}
    finally:
        await purge_dashboard(did)


async def test_widget_grant_foreign_widget_rejected(client, admin_headers, seed_dataset):
    """widget-грант с виджетом из ДРУГОГО дашборда → отклонён (виджет не найден в
    этом дашборде → 404 по маппингу _bad; главное — грант не создаётся)."""
    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_wrls_a"})
    da = r.json()["id"]
    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_wrls_b"})
    db_ = r.json()["id"]
    try:
        pid = (await client.post(f"/dashboards/{db_}/pages", headers=admin_headers, json={"name": "P"})).json()["id"]
        foreign_w = (await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                     json={"name": "X", "widget_type": "kpi", "config": {"dataset_code": "t_ds", "value_field": "plan"}})).json()["id"]
        # пытаемся выдать грант на виджет чужого дашборда через дашборд da
        r = await client.post(f"/dashboards/{da}/grants", headers=admin_headers,
                              json={"grantee_type": "role", "role_id": None, "scope": "widget", "widget_id": foreign_w})
        assert r.status_code in (400, 404)
    finally:
        await purge_dashboard(da)
        await purge_dashboard(db_)
