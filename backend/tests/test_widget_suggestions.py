"""Рекомендательная система (часть A, 2026-08-04): delta-aware предложения
виджетов — GET /widgets/suggestions не повторяет то, что для этого же
датасета уже построено ГДЕ УГОДНО в организации (не только на текущем
дашборде — датасет однозначно принадлежит одному объекту)."""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import purge_dashboard


async def _suggest(client, headers, dataset_code):
    r = await client.get("/widgets/suggestions", headers=headers, params={"dataset_code": dataset_code})
    assert r.status_code == 200, r.text
    return r.json()


def _has_kpi_plan(specs):
    return any(s["widget_type"] == "kpi" and s["config"].get("value_field") == "plan" for s in specs)


async def test_suggestions_exclude_already_built_widgets(client, admin_headers, seed_dataset, ids):
    """suggest_widgets требует dataset_release_fields+canonical_fields
    (метаданные полей от ingestion) — `seed_dataset` их не заводит (вставляет
    dataset_values напрямую, в обход конвейера распознавания), поэтому
    заводим их здесь же, локально для этого теста."""
    from app import db
    async with db.acquire() as conn:
        rel = await conn.fetchrow(
            "select id, object_id from dataset_releases where organization_id=$1 and code='t_ds' "
            "and status<>'superseded' order by reporting_period_start desc limit 1", ids["org"])
        await conn.execute(
            "insert into canonical_fields(object_id,code,name,data_type) values($1,'plan','План','number'),($1,'fact','Факт','number') "
            "on conflict (object_id,code) do nothing", rel["object_id"])
        await conn.execute(
            "insert into dataset_release_fields(dataset_release_id,canonical_field_code) values($1,'plan'),($1,'fact') "
            "on conflict (dataset_release_id,canonical_field_code) do nothing", rel["id"])
    try:
        await _run_suggestions_scenario(client, admin_headers)
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from canonical_fields where object_id=$1 and code in ('plan','fact')", rel["object_id"])
            await conn.execute("delete from dataset_release_fields where dataset_release_id=$1", rel["id"])


async def _run_suggestions_scenario(client, admin_headers):
    r0 = await _suggest(client, admin_headers, "t_ds")
    assert r0["already_built"] == 0
    assert r0["total_candidates"] == len(r0["specs"])
    assert _has_kpi_plan(r0["specs"])  # изначально КPI по 'plan' предлагается

    d = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_sugg_d1"})).json()["id"]
    try:
        pid = (await client.post(f"/dashboards/{d}/pages", headers=admin_headers, json={"name": "Обзор"})).json()["id"]
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "Σ plan", "widget_type": "kpi", "config": {"dataset_code": "t_ds", "value_field": "plan"},
            "position_x": 0, "position_y": 0, "width": 3, "height": 3})

        r1 = await _suggest(client, admin_headers, "t_ds")
        assert r1["already_built"] == 1
        assert r1["total_candidates"] == r0["total_candidates"]
        assert len(r1["specs"]) == len(r0["specs"]) - 1
        assert not _has_kpi_plan(r1["specs"])  # уже построенный КPI по 'plan' больше не предлагается

        # на ДРУГОМ дашборде — та же организация, тот же датасет — исключение всё равно действует
        d2 = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_sugg_d2"})).json()["id"]
        try:
            r2 = await _suggest(client, admin_headers, "t_ds")
            assert not _has_kpi_plan(r2["specs"])
        finally:
            await purge_dashboard(d2)
    finally:
        await purge_dashboard(d)

    # после удаления виджета (вместе с дашбордом) предложение снова появляется
    r3 = await _suggest(client, admin_headers, "t_ds")
    assert r3["already_built"] == 0
    assert _has_kpi_plan(r3["specs"])
