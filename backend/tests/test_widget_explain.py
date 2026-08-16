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
