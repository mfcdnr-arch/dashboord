"""Волна D: папки для дашбордов («банк отделов») — folder_id на дашборде,
фильтр списка по папке, перемещение (POST /dashboards/{id}/folder)."""
import pytest

from app import db

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import purge_dashboard


async def test_move_dashboard_to_folder_and_filter(client, admin_headers):
    obj = (await client.post("/objects", headers=admin_headers, json={"name": "ztest_wd_obj"})).json()
    folder = (await client.post(f"/objects/{obj['id']}/folders", headers=admin_headers, json={"name": "ztest_wd_folder"})).json()
    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_wd_dash"})).json()["id"]
    try:
        # изначально без папки
        d = (await client.get(f"/dashboards/{did}", headers=admin_headers)).json()["dashboard"]
        assert d["folder_id"] is None

        r = await client.post(f"/dashboards/{did}/folder", headers=admin_headers, json={"folder_id": folder["id"]})
        assert r.status_code == 200 and r.json()["folder_id"] == folder["id"]

        d = (await client.get(f"/dashboards/{did}", headers=admin_headers)).json()["dashboard"]
        assert d["folder_id"] == folder["id"]
        assert d["folder_name"] == "ztest_wd_folder"
        assert d["object_name"] == "ztest_wd_obj"

        # фильтр списка по конкретной папке находит дашборд
        r = await client.get("/dashboards", headers=admin_headers, params={"folder_id": folder["id"]})
        ids = {x["id"] for x in r.json()["items"]}
        assert did in ids
        item = next(x for x in r.json()["items"] if x["id"] == did)
        assert item["folder_name"] == "ztest_wd_folder"

        # folder_id='none' — дашборд БЕЗ папки, наш туда уже не попадает
        r = await client.get("/dashboards", headers=admin_headers, params={"q": "ztest_wd_dash", "folder_id": "none"})
        assert did not in {x["id"] for x in r.json()["items"]}

        # убрать из папки
        r = await client.post(f"/dashboards/{did}/folder", headers=admin_headers, json={"folder_id": None})
        assert r.status_code == 200 and r.json()["folder_id"] is None
        d = (await client.get(f"/dashboards/{did}", headers=admin_headers)).json()["dashboard"]
        assert d["folder_id"] is None and d["folder_name"] is None

        r = await client.get("/dashboards", headers=admin_headers, params={"q": "ztest_wd_dash", "folder_id": "none"})
        assert did in {x["id"] for x in r.json()["items"]}
    finally:
        await purge_dashboard(did)
        # Чистим напрямую: DELETE объекта/папки отказывает на непустых, а здесь
        # в папке ещё числится дашборд (его удаляет purge_dashboard выше).
        async with db.acquire() as conn:
            await conn.execute("delete from folders where id=$1::uuid", folder["id"])
            await conn.execute("delete from objects where id=$1::uuid", obj["id"])


async def test_move_dashboard_invalid_folder_404(client, admin_headers):
    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_wd_badfolder"})).json()["id"]
    try:
        r = await client.post(f"/dashboards/{did}/folder", headers=admin_headers,
                              json={"folder_id": "00000000-0000-0000-0000-000000000000"})
        assert r.status_code == 404
    finally:
        await purge_dashboard(did)


async def test_move_dashboard_requires_manage_role(client, admin_headers, viewer):
    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_wd_viewerdenied"})).json()["id"]
    try:
        r = await client.post(f"/dashboards/{did}/folder", headers=viewer["headers"], json={"folder_id": None})
        assert r.status_code == 403
    finally:
        await purge_dashboard(did)
