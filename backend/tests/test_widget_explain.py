"""Подсказка ⓘ отвечает «что это за цифра», а не «что такое карточка».

Раньше значок объяснял ТИП виджета — то, что и так видно. Человек, глядя на
«929 825», спрашивает другое: что это за число, откуда взято и можно ли ему
верить. Теперь подсказка называет показатель или графу формы, источник,
способ сворачивания строк и — для метрик — состояние согласования формулы.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db


async def _page(client, headers, name):
    did = (await client.post("/dashboards", headers=headers, json={"name": name})).json()["id"]
    pid = (await client.post(f"/dashboards/{did}/pages", headers=headers,
                             json={"name": "Стр"})).json()["id"]
    return did, pid


async def _cleanup(did):
    async with db.acquire() as conn:
        await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
        await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
        await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
        await conn.execute("delete from dashboards where id=$1::uuid", did)


async def test_explain_names_the_source_column(client, admin_headers, seed_dataset, ids):
    """Для графы формы: имя графы, форма-источник и способ свёртки строк."""
    async with db.acquire() as conn:
        # Фикстура заводит значения в обход конвейера, без справочника полей —
        # подсказке нужно человеческое имя графы, поэтому заводим его здесь.
        obj = await conn.fetchval("select object_id from dataset_releases where code=$1 limit 1",
                                  seed_dataset["code"])
        await conn.execute(
            "insert into canonical_fields(object_id,code,name,data_type) "
            "values($1,'plan','Плановое количество услуг','number') on conflict do nothing", obj)

    did, pid = await _page(client, admin_headers, "ztest_expl_field")
    try:
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "Σ План", "widget_type": "kpi",
            "config": {"dataset_code": seed_dataset["code"], "value_field": "plan"}})
        w = (await client.get(f"/dashboard-pages/{pid}/widgets", headers=admin_headers)).json()["widgets"][0]
        assert "Плановое количество услуг" in w["explain"]
        assert "сумма по строкам" in w["explain"], "как свёрнуты строки — половина ответа"
    finally:
        await _cleanup(did)
        async with db.acquire() as conn:
            await conn.execute("delete from canonical_fields where object_id=$1 and code='plan'", obj)


async def test_explain_warns_about_draft_formula(client, admin_headers, seed_dataset):
    """Черновик формулы на карточке выглядит как утверждённое значение —
    подсказка обязана об этом сказать."""
    ds = seed_dataset["code"]
    r = await client.post("/metrics", headers=admin_headers, json={
        "code": "ztest_expl_metric", "name": "ztest доля, %", "description": "Доля исполненных заявлений."})
    mid = r.json()["id"]
    await client.post(f"/metrics/{mid}/versions", headers=admin_headers, json={
        "formula": f"PERCENT_OF(SUM(field('{ds}','plan')), SUM(field('{ds}','fact')))", "unit": "%"})

    did, pid = await _page(client, admin_headers, "ztest_expl_metric_dash")
    try:
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "Доля", "widget_type": "kpi", "config": {"metric_code": "ztest_expl_metric"}})
        w = (await client.get(f"/dashboard-pages/{pid}/widgets", headers=admin_headers)).json()["widgets"][0]
        assert "ztest доля, %" in w["explain"]
        assert "Доля исполненных заявлений." in w["explain"], "описание человека важнее формулы"
        assert "PERCENT_OF" in w["explain"], "как считается — тоже часть ответа"
        assert "черновик" in w["explain"], "предварительное значение нельзя показывать молча"
    finally:
        await _cleanup(did)
        async with db.acquire() as conn:
            await conn.execute("delete from metric_versions where metric_id=$1::uuid", mid)
            await conn.execute("delete from metrics where id=$1::uuid", mid)


async def test_explain_is_empty_when_there_is_nothing_to_say(client, admin_headers):
    """Ничего не выдумываем: у аннотации пояснять нечего."""
    did, pid = await _page(client, admin_headers, "ztest_expl_text")
    try:
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "Заметка", "widget_type": "text", "config": {"heading": "Привет"}})
        w = (await client.get(f"/dashboard-pages/{pid}/widgets", headers=admin_headers)).json()["widgets"][0]
        assert not w["explain"]
    finally:
        await _cleanup(did)


async def test_explain_knows_fields_of_every_code_in_the_object(ids):
    """🔴 У объекта два кода наборов — имена граф есть у ОБОИХ (ревью этапа 2, 29.09).

    Первая редакция 24.09 держала один код на объект: у второго набора ⓘ
    карточки говорил «Первичные данные формы» и печатал коды граф.
    """
    import uuid

    from app.modules.dashboards._explain import explain_widgets

    async with db.acquire() as conn:
        obj = await conn.fetchval(
            "insert into objects(organization_id, name, code) values($1,$2,$3) returning id",
            ids["org"], f"ztest_twocodes_{uuid.uuid4().hex[:6]}", f"ztest_tc_{uuid.uuid4().hex[:6]}")
        await conn.execute(
            "insert into canonical_fields(object_id, code, name, data_type) "
            "values($1,'x','Принято заявлений, ед.','number')", obj)
        codes = [f"ztest_tca_{uuid.uuid4().hex[:5]}", f"ztest_tcb_{uuid.uuid4().hex[:5]}"]
        rels = []
        try:
            for code in codes:
                rels.append(await conn.fetchval(
                    "insert into dataset_releases(organization_id, object_id, code, name, "
                    "reporting_period_start, status, created_by) "
                    "values($1,$2,$3,$4,'2026-09-01','released',$5) returning id",
                    ids["org"], obj, code, f"Форма {code}", ids["admin"]))
            widgets = [{"id": code, "widget_type": "kpi",
                        "config": {"dataset_code": code, "value_field": "x"}} for code in codes]
            texts = await explain_widgets(conn, ids["org"], widgets)
            for code in codes:
                assert "Принято заявлений, ед." in texts[code], (code, texts.get(code))
        finally:
            await conn.execute("delete from dataset_releases where id = any($1::uuid[])", rels)
            await conn.execute("delete from canonical_fields where object_id=$1", obj)
            await conn.execute("delete from objects where id=$1", obj)
