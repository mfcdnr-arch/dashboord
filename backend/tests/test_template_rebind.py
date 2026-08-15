"""Тиражирование дашборда на другой объект: перепривязка по именам показателей.

Когда пойдут районы или вторая форма, дашборд должен переноситься, а не
собираться заново двадцать раз. Мешает одно: у другого объекта СВОИ коды
показателей — они выводятся из заголовков его формы. Перенесённый как есть
виджет показал бы «нет данных», причём на каждом виджете по отдельности.

Сопоставляем по именам показателей и честно возвращаем то, что не нашлось:
неверно сопоставленный показатель опаснее отсутствующего, потому что он
выглядит рабочим.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

import pytest_asyncio

from app import db
from app.modules.dashboards import _templates


def test_remap_touches_fields_series_and_lists():
    """Перепривязка достаёт поля везде, где они бывают, а не только dataset_code."""
    cfg = {
        "dataset_code": "old_ds", "value_field": "old_a",
        "value_fields": ["old_a", "old_b"],
        "plan_field": "old_a", "fact_field": "old_b",
        "series": [{"dataset_code": "old_ds", "value_field": "old_b", "label": "Б"}],
        "metric_code": "old_m",
    }
    out = _templates._remap_config(
        cfg, {"old_ds": "new_ds"}, {"old_m": "new_m"}, {"old_a": "new_a", "old_b": "new_b"})
    assert out["dataset_code"] == "new_ds"
    assert out["value_field"] == "new_a"
    assert out["value_fields"] == ["new_a", "new_b"]
    assert out["plan_field"] == "new_a" and out["fact_field"] == "new_b"
    assert out["series"][0] == {"dataset_code": "new_ds", "value_field": "new_b", "label": "Б"}
    assert out["metric_code"] == "new_m"
    # Неизвестные коды остаются как есть — молча подставлять «похожее» нельзя.
    assert _templates._remap_config({"value_field": "zzz"}, {}, {}, {})["value_field"] == "zzz"


def test_template_codes_collect_fields_from_everywhere():
    spec = {"pages": [{"widgets": [
        {"config": {"dataset_code": "ds", "value_fields": ["a", "b"]}},
        {"config": {"series": [{"dataset_code": "ds2", "value_field": "c"}]}},
        {"config": {"plan_field": "d", "fact_field": "e", "metric_code": "m"}},
    ]}]}
    got = _templates._template_codes(spec)
    assert got["datasets"] == ["ds", "ds2"]
    assert got["fields"] == ["a", "b", "c", "d", "e"]
    assert got["metrics"] == ["m"]


@pytest_asyncio.fixture
async def two_objects(ids):
    """Два объекта с ОДИНАКОВЫМИ по смыслу показателями, но разными кодами."""
    async with db.acquire() as conn:
        uid = await conn.fetchval("select id from users where login='admin'")
        made = {}
        for key, (obj_name, code, fields) in {
            "src": ("ztest_reb_src", "ztest_reb_a",
                    [("obr_a", "Количество обращений"), ("uved_a", "Количество уведомлений")]),
            "dst": ("ztest_reb_dst", "ztest_reb_b",
                    [("x1", "Количество обращений"), ("x2", "Количество уведомлений")]),
        }.items():
            oid = await conn.fetchval(
                "insert into objects(organization_id, name, created_by) values($1,$2,$3) returning id",
                ids["org"], obj_name, uid)
            rel = await conn.fetchval(
                "insert into dataset_releases(organization_id, object_id, code, name, status, "
                "reporting_period_start, created_by) "
                "values($1,$2,$3,'Форма','validated','2026-07-22',$4) returning id",
                ids["org"], oid, code, uid)
            for fcode, fname in fields:
                await conn.execute(
                    "insert into canonical_fields(object_id, code, name, data_type, created_by) "
                    "values($1,$2,$3,'number',$4)", oid, fcode, fname, uid)
                await conn.execute(
                    "insert into dataset_release_fields(dataset_release_id, canonical_field_code) "
                    "values($1,$2)", rel, fcode)
                await conn.execute(
                    "insert into dataset_values(dataset_release_id, row_index, row_label, "
                    "canonical_field_code, value_number) values($1,0,'ДНР',$2,100)", rel, fcode)
            made[key] = {"object_id": str(oid), "code": code}
    yield made
    async with db.acquire() as conn:
        for m in made.values():
            await conn.execute("delete from dataset_values where dataset_release_id in "
                               "(select id from dataset_releases where object_id=$1::uuid)", m["object_id"])
            await conn.execute("delete from dataset_release_fields where dataset_release_id in "
                               "(select id from dataset_releases where object_id=$1::uuid)", m["object_id"])
            await conn.execute("delete from dataset_releases where object_id=$1::uuid", m["object_id"])
            await conn.execute("delete from canonical_fields where object_id=$1::uuid", m["object_id"])
            await conn.execute("delete from objects where id=$1::uuid", m["object_id"])


async def test_template_binds_to_another_object_by_names(client, admin_headers, two_objects):
    """Шаблон одного объекта ложится на другой: коды разные, имена те же."""
    src, dst = two_objects["src"], two_objects["dst"]

    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_reb_dash"})
    did = r.json()["id"]
    r = await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "Обзор"})
    pid = r.json()["id"]
    await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
        "name": "Обращения", "widget_type": "kpi",
        "config": {"dataset_code": src["code"], "value_field": "obr_a"}})
    await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
        "name": "Сравнение", "widget_type": "compare",
        "config": {"dataset_code": src["code"], "value_fields": ["obr_a", "uved_a"]}})

    r = await client.post(f"/dashboards/{did}/save-template", headers=admin_headers,
                          json={"name": "ztest_reb_tpl"})
    tid = r.json()["id"]
    new_did = None
    try:
        r = await client.get(f"/dashboard-templates/{tid}/bindings?object_id={dst['object_id']}",
                             headers=admin_headers)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["dataset_map"] == {src["code"]: dst["code"]}
        assert b["field_map"] == {"obr_a": "x1", "uved_a": "x2"}, b
        assert b["missing"] == [], b

        r = await client.post(f"/dashboard-templates/{tid}/instantiate", headers=admin_headers,
                              json={"name": "ztest_reb_copy", "dataset_map": b["dataset_map"],
                                    "field_map": b["field_map"]})
        assert r.status_code == 201, r.text
        new_did = r.json()["dashboard_id"]

        async with db.acquire() as conn:
            cfgs = [r["config"] for r in await conn.fetch(
                "select config::text as config from widgets where dashboard_id=$1::uuid", new_did)]
        joined = " ".join(cfgs)
        assert dst["code"] in joined and src["code"] not in joined, joined
        assert '"x1"' in joined and '"obr_a"' not in joined, joined
    finally:
        async with db.acquire() as conn:
            for d in [x for x in (did, new_did) if x]:
                await conn.execute("delete from widgets where dashboard_id=$1::uuid", d)
                await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", d)
                await conn.execute("delete from securable_objects where object_id=$1::uuid", d)
                await conn.execute("delete from dashboards where id=$1::uuid", d)
            await conn.execute("delete from dashboard_templates where id=$1::uuid", tid)


async def test_missing_indicator_is_reported_not_guessed(client, admin_headers, two_objects, ids):
    """Показателя нет у целевого объекта — он попадает в «не найдено», а не в догадки."""
    src, dst = two_objects["src"], two_objects["dst"]
    async with db.acquire() as conn:
        uid = await conn.fetchval("select id from users where login='admin'")
        rel = await conn.fetchval(
            "select id from dataset_releases where object_id=$1::uuid", src["object_id"])
        await conn.execute(
            "insert into canonical_fields(object_id, code, name, data_type, created_by) "
            "values($1,'only_src','Показатель только у первого','number',$2)", src["object_id"], uid)
        await conn.execute(
            "insert into dataset_release_fields(dataset_release_id, canonical_field_code) "
            "values($1,'only_src')", rel)

    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_reb_dash2"})
    did = r.json()["id"]
    r = await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "Обзор"})
    pid = r.json()["id"]
    await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
        "name": "Только тут", "widget_type": "kpi",
        "config": {"dataset_code": src["code"], "value_field": "only_src"}})
    r = await client.post(f"/dashboards/{did}/save-template", headers=admin_headers,
                          json={"name": "ztest_reb_tpl2"})
    tid = r.json()["id"]
    try:
        r = await client.get(f"/dashboard-templates/{tid}/bindings?object_id={dst['object_id']}",
                             headers=admin_headers)
        b = r.json()
        assert "only_src" not in b["field_map"], "подставлять «похожее» нельзя"
        assert any(m["from"] == "only_src" for m in b["missing"]), b
        assert any("только у первого" in (m.get("from_name") or "").lower() for m in b["missing"])
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
            await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)
            await conn.execute("delete from dashboard_templates where id=$1::uuid", tid)
