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


# --- Фильтр «какие дашборды построены на данных этого отчёта» ---------------- #
# Под одним кодом лежит ВЕСЬ ряд недельных файлов, поэтому совпадений два вида,
# и оба настоящие: дашборд закреплён именно за этой отчётной датой либо просто
# читает эту форму. Тест держит и отбор, и различие между ними — без второго
# список выглядел бы одинаково для любого файла папки.
async def test_dashboards_filtered_by_document(client, admin_headers, ids):
    async with db.acquire() as conn:
        await _drop_doc_filter(conn)
        oid = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,'ztest_df_obj') returning id", ids["org"])
        fid = await conn.fetchval(
            "insert into folders(organization_id,object_id,name) values($1,$2,'ztest_df_folder') returning id",
            ids["org"], oid)
        doc = await conn.fetchval(
            "insert into documents(organization_id, folder_id, original_filename, source_type, "
            "reporting_period_start, uploaded_by) values($1,$2,'ztest_df.xlsx','xlsx','2026-04-06',$3) returning id",
            ids["org"], fid, ids["admin"])
        ver = await conn.fetchval(
            "insert into document_versions(document_id, version_no, storage_path, checksum, "
            "file_size_bytes, uploaded_by) values($1,1,'documents/ztest_df','ztest_df_sum',10,$2) returning id",
            doc, ids["admin"])
        await conn.execute(
            "insert into dataset_releases(organization_id, code, name, status, reporting_period_start, "
            "created_by, object_id, source_document_version_id) "
            "values($1,'ztest_df_ds','Форма','released','2026-04-06',$2,$3,$4)",
            ids["org"], ids["admin"], oid, ver)

    made = []
    try:
        # (1) читает форму, (2) закреплён на этом отчёте, (3) не связан вовсе
        for name, cfg in (
            ("ztest_df_uses", {"dataset_code": "ztest_df_ds", "value_field": "plan"}),
            ("ztest_df_pinned", {"dataset_code": "ztest_df_ds", "value_field": "plan",
                                 "period": "2026-04-06"}),
            ("ztest_df_other", {"dataset_code": "t_ds", "value_field": "plan"}),
        ):
            r = await client.post("/dashboards", headers=admin_headers, json={"name": name, "force": True})
            did = r.json()["id"]
            made.append(did)
            page = await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "Стр"})
            await client.post(f"/dashboard-pages/{page.json()['id']}/widgets", headers=admin_headers,
                              json={"name": "ztest виджет", "widget_type": "kpi", "config": cfg})

        res = (await client.get(f"/dashboards?document_id={doc}&limit=50", headers=admin_headers)).json()
        names = {i["name"]: i for i in res["items"]}
        assert "ztest_df_uses" in names and "ztest_df_pinned" in names
        assert "ztest_df_other" not in names, "чужие данные в фильтр попадать не должны"

        assert names["ztest_df_pinned"]["pinned_to_document"] is True, \
            "собранный по этому отчёту обязан отличаться от читающего форму"
        assert names["ztest_df_uses"]["pinned_to_document"] is False

        # Без фильтра признак не считается — лишний подзапрос на каждый список.
        plain = (await client.get("/dashboards?limit=50", headers=admin_headers)).json()
        assert "pinned_to_document" not in plain["items"][0]
    finally:
        for did in made:
            await purge_dashboard(did)
        async with db.acquire() as conn:
            await _drop_doc_filter(conn)


async def _drop_doc_filter(conn):
    await conn.execute("delete from dataset_releases where code='ztest_df_ds'")
    await conn.execute("delete from document_versions where document_id in "
                       "(select id from documents where original_filename='ztest_df.xlsx')")
    await conn.execute("delete from documents where original_filename='ztest_df.xlsx'")
    await conn.execute("delete from folders where name='ztest_df_folder'")
    await conn.execute("delete from objects where name='ztest_df_obj'")
