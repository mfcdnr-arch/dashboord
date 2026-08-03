"""Витрины (волна E): подборка из N целых дашбордов на одном экране.

Проверяем: CRUD, состав фильтруется RLS дашбордов (чужой/неопубликованный
дашборд внутри витрины для обычного пользователя не палится), реордер,
запрет дубликата, доступ на запись только staff."""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import purge_dashboard


async def test_showcase_crud_and_reorder(client, admin_headers, viewer):
    d1 = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_sc_d1"})).json()["id"]
    d2 = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_sc_d2"})).json()["id"]
    try:
        await client.post(f"/dashboards/{d1}/pages", headers=admin_headers, json={"name": "Обзор"})
        await client.post(f"/dashboards/{d1}/grants", headers=admin_headers, json={"grantee_type": "user", "user_id": viewer["id"]})
        await client.post(f"/dashboards/{d1}/publish", headers=admin_headers)
        await client.post(f"/dashboards/{d2}/grants", headers=admin_headers, json={"grantee_type": "user", "user_id": viewer["id"]})
        await client.post(f"/dashboards/{d2}/publish", headers=admin_headers)

        sid = (await client.post("/showcases", headers=admin_headers, json={"name": "ztest_showcase"})).json()["id"]

        r = await client.post(f"/showcases/{sid}/items", headers=admin_headers, json={"dashboard_id": d1})
        assert r.status_code == 201
        item1 = r.json()["id"]
        r = await client.post(f"/showcases/{sid}/items", headers=admin_headers, json={"dashboard_id": d2})
        assert r.status_code == 201
        item2 = r.json()["id"]

        # дубликат отклонён
        r = await client.post(f"/showcases/{sid}/items", headers=admin_headers, json={"dashboard_id": d1})
        assert r.status_code == 400

        # список витрин показывает items_count
        r = await client.get("/showcases", headers=admin_headers)
        assert any(s["id"] == sid and s["items_count"] == 2 for s in r.json())

        # viewer (обычный пользователь, но оба дашборда опубликованы+грант) видит оба, d1 с первой страницей
        r = await client.get(f"/showcases/{sid}", headers=viewer["headers"])
        assert r.status_code == 200
        items = r.json()["items"]
        assert [it["dashboard_id"] for it in items] == [d1, d2]
        assert items[0]["page_name"] == "Обзор" and items[0]["page_id"]

        # реордер: d2 выше d1
        r = await client.post(f"/showcases/{sid}/reorder", headers=admin_headers, json={"item_id": item2, "direction": "up"})
        assert r.status_code == 200
        items = (await client.get(f"/showcases/{sid}", headers=admin_headers)).json()["items"]
        assert [it["dashboard_id"] for it in items] == [d2, d1]

        # убрать элемент
        assert (await client.delete(f"/showcases/{sid}/items/{item1}", headers=admin_headers)).status_code == 204
        items = (await client.get(f"/showcases/{sid}", headers=admin_headers)).json()["items"]
        assert len(items) == 1 and items[0]["dashboard_id"] == d2

        # удалить витрину
        assert (await client.delete(f"/showcases/{sid}", headers=admin_headers)).status_code == 204
        assert (await client.get(f"/showcases/{sid}", headers=admin_headers)).status_code == 404
    finally:
        await purge_dashboard(d1)
        await purge_dashboard(d2)


async def test_showcase_hides_inaccessible_dashboard(client, admin_headers, viewer):
    """Черновик без гранта — виден admin'у в составе, но не появляется у viewer (не палим существование)."""
    d_visible = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_sc_visible"})).json()["id"]
    d_hidden = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_sc_hidden"})).json()["id"]
    try:
        await client.post(f"/dashboards/{d_visible}/grants", headers=admin_headers, json={"grantee_type": "user", "user_id": viewer["id"]})
        await client.post(f"/dashboards/{d_visible}/publish", headers=admin_headers)
        # d_hidden остаётся draft без гранта — viewer не должен его увидеть

        sid = (await client.post("/showcases", headers=admin_headers, json={"name": "ztest_showcase_mixed"})).json()["id"]
        await client.post(f"/showcases/{sid}/items", headers=admin_headers, json={"dashboard_id": d_visible})
        await client.post(f"/showcases/{sid}/items", headers=admin_headers, json={"dashboard_id": d_hidden})

        r = await client.get(f"/showcases/{sid}", headers=admin_headers)
        assert len(r.json()["items"]) == 2  # admin (привилегированный) видит оба

        r = await client.get(f"/showcases/{sid}", headers=viewer["headers"])
        ids = [it["dashboard_id"] for it in r.json()["items"]]
        assert ids == [d_visible]  # скрытый молча отфильтрован

        await client.delete(f"/showcases/{sid}", headers=admin_headers)
    finally:
        await purge_dashboard(d_visible)
        await purge_dashboard(d_hidden)


async def test_showcase_write_requires_manage_role(client, admin_headers, viewer):
    sid = (await client.post("/showcases", headers=admin_headers, json={"name": "ztest_showcase_perm"})).json()["id"]
    d = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_sc_perm_dash"})).json()["id"]
    try:
        assert (await client.post("/showcases", headers=viewer["headers"], json={"name": "нельзя"})).status_code == 403
        assert (await client.post(f"/showcases/{sid}/items", headers=viewer["headers"], json={"dashboard_id": d})).status_code == 403
        assert (await client.delete(f"/showcases/{sid}", headers=viewer["headers"])).status_code == 403
        # viewer может СМОТРЕТЬ список/детали (без прав на запись)
        assert (await client.get("/showcases", headers=viewer["headers"])).status_code == 200
        assert (await client.get(f"/showcases/{sid}", headers=viewer["headers"])).status_code == 200
    finally:
        await purge_dashboard(d)
        await client.delete(f"/showcases/{sid}", headers=admin_headers)
