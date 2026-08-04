"""Рекомендательная система, часть B (2026-08-04): предложения производных
метрик. Область — объединение «метрики дашборда» (виджеты со ссылкой на
metric_code) + «метрики объекта» (через folder_id дашборда), обе резолвятся
из dashboard_id. Проверяем все 7 одобренных типов + дедуп уже существующего."""
import pytest

from app import db

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import purge_dashboard


async def _create_metric(client, headers, code, name, formula, unit=None):
    m = (await client.post("/metrics", headers=headers, json={"code": code, "name": name})).json()
    r = await client.post(f"/metrics/{m['id']}/versions", headers=headers,
                          json={"formula": formula, "unit": unit})
    assert r.status_code == 201, r.text
    return m


def _types(specs):
    return {s["type"] for s in specs}


def _codes_in_based_on(specs, spec_type):
    out = set()
    for s in specs:
        if s["type"] == spec_type:
            out.update(s["based_on"])
    return out


async def test_suggest_derived_metrics_full_scenario(client, admin_headers, seed_dataset, ids):
    await _create_metric(client, admin_headers, "ztest_rec_plan", "План М", "SUM(field('t_ds','plan'))", "шт")
    await _create_metric(client, admin_headers, "ztest_rec_fact", "Факт М", "SUM(field('t_ds','fact'))", "шт")
    await _create_metric(client, admin_headers, "ztest_rec_extra", "Доп П", "SUM(field('t_ds','plan'))", "шт")

    # ВАЖНО: папка должна быть под t_obj — тем же объектом, что владеет датасетом
    # t_ds (см. seed_dataset), иначе object-scope не подтянет fact/extra.
    async with db.acquire() as conn:
        obj_id = await conn.fetchval("select id from objects where name='t_obj' and organization_id=$1", ids["org"])
    obj = {"id": str(obj_id)}
    folder = (await client.post(f"/objects/{obj['id']}/folders", headers=admin_headers, json={"name": "ztest_rec_folder"})).json()

    d = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_rec_dashboard"})).json()["id"]
    try:
        page_id = (await client.post(f"/dashboards/{d}/pages", headers=admin_headers, json={"name": "Обзор"})).json()["id"]
        await client.post(f"/dashboard-pages/{page_id}/widgets", headers=admin_headers, json={
            "name": "Σ План", "widget_type": "kpi",
            "config": {"metric_code": "ztest_rec_plan", "target": 200},
            "position_x": 0, "position_y": 0, "width": 3, "height": 3})

        # без привязки к папке/объекту — только dashboard-scope (виджет ссылается на plan)
        r_before = await client.get("/metrics/suggestions", headers=admin_headers, params={"dashboard_id": d})
        assert r_before.status_code == 200, r_before.text
        based_on_before = set()
        for s in r_before.json()["specs"]:
            based_on_before.update(s["based_on"])
        assert "ztest_rec_plan" in based_on_before
        assert "ztest_rec_extra" not in based_on_before  # ещё не в scope — нет ни виджета, ни привязки к объекту

        # привязываем дашборд к папке объекта — object-scope подтягивает fact/extra тоже
        r = await client.post(f"/dashboards/{d}/folder", headers=admin_headers, json={"folder_id": folder["id"]})
        assert r.status_code == 200

        r_after = await client.get("/metrics/suggestions", headers=admin_headers, params={"dashboard_id": d})
        assert r_after.status_code == 200, r_after.text
        data = r_after.json()
        assert data["candidates_count"] == 3
        specs = data["specs"]
        types = _types(specs)
        assert {"period_compare", "yoy", "running_total", "deviation", "plan_fact", "diff", "share"} <= types

        # период-к-периоду/год-к-году/накопительный итог — на все 3 (t_ds имеет 2 периода)
        for t in ("period_compare", "yoy", "running_total"):
            assert {s["based_on"][0] for s in specs if s["type"] == t} == \
                {"ztest_rec_plan", "ztest_rec_fact", "ztest_rec_extra"}

        # отклонение от цели — только у ztest_rec_plan (у него target=200 на виджете)
        assert _codes_in_based_on(specs, "deviation") == {"ztest_rec_plan"}
        dev = next(s for s in specs if s["type"] == "deviation")
        assert "200" in dev["formula"]

        # план/факт-пара по названию
        pf = next(s for s in specs if s["type"] == "plan_fact")
        assert set(pf["based_on"]) == {"ztest_rec_plan", "ztest_rec_fact"}
        assert "PLAN_FACT_PCT" in pf["formula"]

        # разница/доля — родственные метрики (общий датасет t_ds)
        diff_pairs = [set(s["based_on"]) for s in specs if s["type"] == "diff"]
        assert any({"ztest_rec_plan", "ztest_rec_fact"} == p for p in diff_pairs)

        # у каждого предложения есть уникальный черновой code
        codes = [s["code"] for s in specs]
        assert len(codes) == len(set(codes))

        # дедуп: формула, уже существующая как метрика (берём ТОЧНЫЙ текст только
        # что предложенной diff-формулы plan/fact, порядок операндов канонический
        # — по сортировке кодов, не обязательно plan-fact), не предлагается повторно
        plan_fact_diff = next(s for s in specs if s["type"] == "diff" and set(s["based_on"]) == {"ztest_rec_plan", "ztest_rec_fact"})
        await _create_metric(client, admin_headers, "ztest_rec_diff_existing", "Уже есть", plan_fact_diff["formula"])
        r_dedup = await client.get("/metrics/suggestions", headers=admin_headers, params={"dashboard_id": d})
        specs2 = r_dedup.json()["specs"]
        assert not any(set(s["based_on"]) == {"ztest_rec_plan", "ztest_rec_fact"} and s["type"] == "diff" for s in specs2)
    finally:
        await purge_dashboard(d)
        async with db.acquire() as conn:
            await conn.execute("delete from metrics where code like 'ztest_rec_%'")
            await conn.execute("delete from folders where id=$1::uuid", folder["id"])
            # obj = t_obj — общий, СЕССИОННЫЙ объект seed_dataset; его саму НЕ удаляем
            # (удалит teardown фикстуры), только созданную здесь папку.


async def test_suggestions_requires_manage_role(client, admin_headers, viewer, seed_dataset):
    d = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_rec_perm"})).json()["id"]
    try:
        r = await client.get("/metrics/suggestions", headers=viewer["headers"], params={"dashboard_id": d})
        assert r.status_code == 403
    finally:
        await purge_dashboard(d)
