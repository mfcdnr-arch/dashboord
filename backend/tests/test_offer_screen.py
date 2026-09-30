"""Этап 4: экран предложения виджетов (решения заказчика 23.09.2026).

«В существующий дашборд — отдельной НОВОЙ страницей», у каждого кандидата —
маленький предпросмотр настоящего виджета, «Создано N — отменить». Отмена —
узкое исключение из правила «удаляет только суперадминистратор» (11.08): своё,
только что, только черновик и ровно то, что сборка создала.
"""
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
