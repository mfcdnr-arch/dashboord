"""Батч-эндпоинт данных страницы: данные всех виджетов за 1 запрос."""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture
def _dash():
    return None


async def test_page_data_batch(client, admin_headers, seed_dataset):
    # создать дашборд → страницу → 2 виджета, затем забрать все данные одним запросом
    from conftest import purge_dashboard
    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_batch"})
    did = r.json()["id"]
    try:
        r = await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "P"})
        pid = r.json()["id"]
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                          json={"name": "k", "widget_type": "kpi", "config": {"dataset_code": "t_ds", "value_field": "plan"}})
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                          json={"name": "t", "widget_type": "table", "config": {"dataset_code": "t_ds"}})
        r = await client.get(f"/dashboard-pages/{pid}/data", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert len(body["widgets"]) == 2
        types = {w["data"]["type"] for w in body["widgets"] if "data" in w}
        assert types == {"kpi", "table"}
    finally:
        await purge_dashboard(did)


async def test_page_data_bad_page_404(client, admin_headers):
    r = await client.get("/dashboard-pages/00000000-0000-0000-0000-000000000000/data", headers=admin_headers)
    assert r.status_code in (400, 404)
