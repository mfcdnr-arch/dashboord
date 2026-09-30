"""Этап 4: экран предложения виджетов (решения заказчика 23.09.2026).

«В существующий дашборд — отдельной НОВОЙ страницей», у каждого кандидата —
маленький предпросмотр настоящего виджета, «Создано N — отменить». Отмена —
узкое исключение из правила «удаляет только суперадминистратор» (11.08): своё,
только что, только черновик и ровно то, что сборка создала.
"""
from datetime import date

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db  # noqa: E402
from conftest import purge_dashboard  # noqa: E402
from test_auto_build import _cleanup_fields, _seed_fields  # noqa: E402


async def _count(sql, *args):
    async with db.acquire() as conn:
        return await conn.fetchval(sql, *args)


async def test_into_existing_adds_one_new_page_and_keeps_the_rest(client, admin_headers, seed_dataset, ids):
    """Предложенное ложится ОДНОЙ новой страницей; свои страницы дашборда целы."""
    rel = await _seed_fields(ids["org"])
    obj = str(rel["object_id"])
    host = (await client.post("/dashboards", headers=admin_headers,
                              json={"name": "ztest_offer_host", "force": True})).json()["id"]
    try:
        own = (await client.post(f"/dashboards/{host}/pages", headers=admin_headers,
                                 json={"name": "Своя"})).json()["id"]
        await client.post(f"/dashboard-pages/{own}/widgets", headers=admin_headers,
                          json={"name": "моё", "widget_type": "text", "config": {"text": "x"}})
        plan = (await client.post("/dashboards/auto/plan", headers=admin_headers,
                                  json={"object_id": obj})).json()

        r = await client.post("/dashboards/auto", headers=admin_headers,
                              json={"object_id": obj, "into_dashboard_id": host})
        assert r.status_code == 201, r.text
        out = r.json()
        assert out["dashboard_id"] == host and out["pages"] == 1
        assert out["undo"] == {"dashboard_id": host, "page_ids": [out["page_id"]], "whole": False}
        assert await _count("select count(*) from dashboard_pages where dashboard_id=$1::uuid", host) == 2
        assert await _count("select count(*) from widgets where page_id=$1::uuid", own) == 1, \
            "своя страница дашборда не тронута"
        assert await _count("select count(*) from widgets where page_id=$1::uuid",
                            out["page_id"]) == plan["widgets"], "на новой странице — ровно обещанное"

        # Страницы плана идут друг под другом в своём порядке, а не вперемешку:
        # у каждой отсчёт с нуля, и без сдвига «поток» смешал бы их.
        page_of = {}
        for c in plan["candidates"]:
            if c["build"]:
                page_of.setdefault(c["name"], set()).add(c["page"])
        order = [p["name"] for p in plan["pages"]]
        async with db.acquire() as conn:
            names = [r["name"] for r in await conn.fetch(
                "select name from widgets where page_id=$1::uuid order by position_y, position_x",
                out["page_id"])]
        seq = [order.index(next(iter(page_of[n]))) for n in names if len(page_of.get(n, ())) == 1]
        assert seq == sorted(seq), "виджеты страниц плана не должны перемешаться"

        r2 = await client.post("/dashboards/auto", headers=admin_headers,
                               json={"object_id": obj, "into_dashboard_id": host})
        assert r2.status_code == 201, r2.text
        assert r2.json()["page_names"][0].endswith("(2)"), "второй раз — страница с другим именем"
    finally:
        await purge_dashboard(host)
        await _cleanup_fields(rel)


async def test_undo_new_dashboard_and_added_page(client, admin_headers, seed_dataset, ids):
    """Отмена убирает ровно созданное: дашборд целиком или добавленную страницу."""
    rel = await _seed_fields(ids["org"])
    obj = str(rel["object_id"])
    host = (await client.post("/dashboards", headers=admin_headers,
                              json={"name": "ztest_offer_undo_host", "force": True})).json()["id"]
    made = None
    try:
        r = await client.post("/dashboards/auto", headers=admin_headers,
                              json={"object_id": obj, "name": "ztest_offer_new", "force": True})
        made = r.json()["dashboard_id"]
        undo = r.json()["undo"]
        assert undo["whole"] is True and undo["dashboard_id"] == made
        u = await client.post("/dashboards/auto/undo", headers=admin_headers, json=undo)
        assert u.status_code == 200 and u.json()["undone"] == "dashboard", u.text
        assert await _count("select count(*) from dashboards where id=$1::uuid", made) == 0
        made = None

        own = (await client.post(f"/dashboards/{host}/pages", headers=admin_headers,
                                 json={"name": "Своя"})).json()["id"]
        r = await client.post("/dashboards/auto", headers=admin_headers,
                              json={"object_id": obj, "into_dashboard_id": host})
        u = await client.post("/dashboards/auto/undo", headers=admin_headers, json=r.json()["undo"])
        assert u.status_code == 200 and u.json()["undone"] == "pages", u.text
        async with db.acquire() as conn:
            left = [str(x["id"]) for x in await conn.fetch(
                "select id from dashboard_pages where dashboard_id=$1::uuid", host)]
        assert left == [own], "осталась только своя страница — чужое отмена не трогает"

        # Страницу ДРУГОГО дашборда через этот не отменить: id страниц
        # сверяются с дашбордом, названным в запросе.
        other = (await client.post("/dashboards", headers=admin_headers,
                                   json={"name": "ztest_offer_other_host", "force": True})).json()["id"]
        try:
            op = (await client.post(f"/dashboards/{other}/pages", headers=admin_headers,
                                    json={"name": "Чужая"})).json()["id"]
            u2 = await client.post("/dashboards/auto/undo", headers=admin_headers,
                                   json={"dashboard_id": host, "page_ids": [op]})
            assert u2.status_code == 404 and "не найдена" in u2.json()["detail"]
            assert await _count("select count(*) from dashboard_pages where id=$1::uuid", op) == 1
        finally:
            await purge_dashboard(other)
    finally:
        if made:
            await purge_dashboard(made)
        await purge_dashboard(host)
        await _cleanup_fields(rel)


async def test_undo_refuses_outside_its_bounds(client, admin_headers, moderator_user, seed_dataset, ids):
    """🔴 Не общее право удаления: чужое, давнее и не черновик — отказ."""
    rel = await _seed_fields(ids["org"])
    obj = str(rel["object_id"])
    made = []
    try:
        async def build(name):
            r = await client.post("/dashboards/auto", headers=admin_headers,
                                  json={"object_id": obj, "name": name, "force": True})
            assert r.status_code == 201, r.text
            made.append(r.json()["dashboard_id"])
            return r.json()["undo"]

        undo = await build("ztest_offer_other")
        u = await client.post("/dashboards/auto/undo", headers=moderator_user["headers"], json=undo)
        assert u.status_code == 400 and "тот, кто её сделал" in u.json()["detail"]

        undo = await build("ztest_offer_old")
        async with db.acquire() as conn:
            await conn.execute("update dashboards set created_at = now() - interval '31 minutes' "
                               "where id=$1::uuid", undo["dashboard_id"])
        u = await client.post("/dashboards/auto/undo", headers=admin_headers, json=undo)
        assert u.status_code == 400 and "30 минут" in u.json()["detail"]

        undo = await build("ztest_offer_published")
        async with db.acquire() as conn:
            await conn.execute("update dashboards set publication_status='published' where id=$1::uuid",
                               undo["dashboard_id"])
        u = await client.post("/dashboards/auto/undo", headers=admin_headers, json=undo)
        assert u.status_code == 400 and "опубликован" in u.json()["detail"]

        assert await _count("select count(*) from dashboards where id = any($1::uuid[])", made) == 3, \
            "ни один отказ ничего не удалил"

        rebuilt = await client.post("/dashboards/auto", headers=admin_headers,
                                    json={"object_id": obj, "dashboard_id": made[0]})
        assert rebuilt.json()["undo"] is None, "пересборку отменить нечем — прежнее уже заменено"
    finally:
        for did in made:
            await purge_dashboard(did)
        await _cleanup_fields(rel)


async def test_candidate_config_drives_a_real_preview(client, admin_headers, seed_dataset, ids):
    """Предпросмотр кандидата — тем же /widgets/preview, что у конструктора."""
    rel = await _seed_fields(ids["org"])
    try:
        plan = (await client.post("/dashboards/auto/plan", headers=admin_headers,
                                  json={"object_id": str(rel["object_id"])})).json()
        cand = next(c for c in plan["candidates"] if c["build"] and c["widget_type"] != "table")
        assert cand["config"].get("dataset_code"), "у кандидата есть настоящая конфигурация"
        r = await client.post("/widgets/preview", headers=admin_headers, json={
            "widget_type": cand["widget_type"], "name": cand["name"], "config": cand["config"]})
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), dict) and "error" not in r.json(), "предпросмотр посчитан без ошибки"
    finally:
        await _cleanup_fields(rel)


async def test_journal_offers_only_the_file_that_brought_a_new_form(client, admin_headers, ids):
    """«Это новая форма, дашбордов по ней нет» — только у файла, с которого форма
    началась; второй недельный файл той же формы предложения не несёт, а
    появившийся дашборд снимает его и у первого (решение заказчика 23.09)."""
    async with db.acquire() as conn:
        # Хвосты прошлого прогона, упавшего на заготовке: иначе объект с тем же
        # именем не заведётся, и тест упадёт не по существу.
        await conn.execute("delete from dataset_releases where code='ztest_offer_ds'")
        await conn.execute("delete from objects where name='ztest_offer_obj'")
        oid = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,'ztest_offer_obj') returning id", ids["org"])
        fid = await conn.fetchval(
            "insert into folders(organization_id,object_id,name) values($1,$2,'ztest_offer_folder') returning id",
            ids["org"], oid)
        docs = []
        for n, (period, made) in enumerate([(date(2026, 4, 6), "now() - interval '2 hours'"),
                                            (date(2026, 4, 13), "now() - interval '1 hour'")]):
            doc = await conn.fetchval(
                "insert into documents(organization_id, folder_id, original_filename, source_type, "
                "reporting_period_start, uploaded_by) values($1,$2,$3,'xlsx',$4::date,$5) returning id",
                ids["org"], fid, f"ztest_offer_{n}.xlsx", period, ids["admin"])
            ver = await conn.fetchval(
                "insert into document_versions(document_id, version_no, storage_path, checksum, "
                "file_size_bytes, uploaded_by) values($1,1,$2,$3,10,$4) returning id",
                doc, f"documents/ztest_offer_{n}", f"ztest_offer_sum{n}", ids["admin"])
            await conn.execute(
                "insert into dataset_releases(organization_id, code, name, status, reporting_period_start, "
                f"created_by, object_id, source_document_version_id, created_at) "
                f"values($1,'ztest_offer_ds','Форма','released',$2::date,$3,$4,$5,{made})",
                ids["org"], period, ids["admin"], oid, ver)
            docs.append(str(doc))
    did = None
    try:
        def offers(items):
            return {i["id"]: i["offer"] for i in items if i["id"] in docs}

        items = (await client.get("/uploads?limit=200", headers=admin_headers)).json()["items"]
        assert offers(items) == {docs[0]: True, docs[1]: False}, \
            "предложение — у файла, принёсшего форму; недельный повтор его не несёт"

        did = (await client.post("/dashboards", headers=admin_headers,
                                 json={"name": "ztest_offer_by_form", "force": True})).json()["id"]
        async with db.acquire() as conn:
            await conn.execute("update dashboards set folder_id=$2 where id=$1::uuid", did, fid)
        items = (await client.get("/uploads?limit=200", headers=admin_headers)).json()["items"]
        assert offers(items) == {docs[0]: False, docs[1]: False}, "дашборд по форме есть — не предлагаем"
    finally:
        if did:
            await purge_dashboard(did)
        async with db.acquire() as conn:
            await conn.execute("delete from dataset_releases where code='ztest_offer_ds'")
            await conn.execute("delete from objects where id=$1", oid)
