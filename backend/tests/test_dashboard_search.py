"""Волна A: даты дашборда в API, поиск дашбордов по дате/названию страницы,
поиск в архиве по дате, счётчик комментариев для условного значка."""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import purge_dashboard


async def test_dashboard_has_updated_at_and_comments_count(client, admin_headers):
    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_wa_dates"})).json()["id"]
    try:
        d = (await client.get(f"/dashboards/{did}", headers=admin_headers)).json()["dashboard"]
        assert d["created_at"]
        assert d["updated_at"]
        assert d["comments_count"] == 0
        await client.post(f"/dashboards/{did}/comments", headers=admin_headers, json={"body": "тест"})
        d2 = (await client.get(f"/dashboards/{did}", headers=admin_headers)).json()["dashboard"]
        assert d2["comments_count"] == 1
    finally:
        await purge_dashboard(did)


async def test_list_dashboards_search_by_page_name(client, admin_headers):
    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_wa_pagesearch"})).json()["id"]
    try:
        await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "ztest_uникальная_страница"})
        r = await client.get("/dashboards", headers=admin_headers, params={"q": "ztest_uникальная"})
        names = {x["name"] for x in r.json()["items"]}
        assert "ztest_wa_pagesearch" in names
    finally:
        await purge_dashboard(did)


async def test_list_dashboards_date_range_filter(client, admin_headers):
    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_wa_daterange"})).json()["id"]
    try:
        r_future = await client.get("/dashboards", headers=admin_headers,
                                    params={"q": "ztest_wa_daterange", "from_date": "2099-01-01"})
        assert r_future.json()["total"] == 0
        r_now = await client.get("/dashboards", headers=admin_headers,
                                 params={"q": "ztest_wa_daterange", "from_date": "2020-01-01"})
        assert r_now.json()["total"] == 1
    finally:
        await purge_dashboard(did)


async def test_archive_search_by_page_name_and_date(client, admin_headers):
    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_wa_archsearch"})).json()["id"]
    aid = None
    try:
        await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "ztest_archпейдж"})
        r = await client.post(f"/dashboards/{did}/archive", headers=admin_headers, json={})
        aid = r.json()["id"]
        found = await client.get("/archive", headers=admin_headers, params={"q": "ztest_archпейдж"})
        assert any(x["id"] == aid for x in found.json())
        none_found = await client.get("/archive", headers=admin_headers, params={"q": "ztest_archпейдж", "from_date": "2099-01-01"})
        assert not any(x["id"] == aid for x in none_found.json())
    finally:
        if aid:
            await client.delete(f"/archive/{aid}", headers=admin_headers)
        await purge_dashboard(did)
