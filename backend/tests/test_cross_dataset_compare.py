"""Сравнение источников (cross_dataset_compare): несколько РАЗНЫХ dataset_code
на одном графике, без формул — только выбором датасет+поле+способ сопоставления.

t_ds: строки Паспорт(100)/ИНН(50)/СНИЛС(30), периоды 2026-01-01/2026-02-01.
t_ds2: строки Паспорт(45)/ИНН(22)/Загранпаспорт(6), те же периоды (объект 't_obj').
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import db, purge_dashboard


async def _preview(client, headers, config):
    r = await client.post("/widgets/preview", headers=headers,
                          json={"widget_type": "cross_dataset_compare", "name": "T", "config": config})
    return r


async def test_row_label_match_merges_categories(client, admin_headers, seed_dataset, seed_dataset2):
    r = await _preview(client, admin_headers, {
        "series": [
            {"dataset_code": "t_ds", "value_field": "plan"},
            {"dataset_code": "t_ds2", "value_field": "plan2"},
        ],
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["type"] == "cross_dataset_compare"
    assert d["match_by"] == "row_label"
    # объединение категорий: Паспорт/ИНН (общие) + СНИЛС (только t_ds) + Загранпаспорт (только t_ds2)
    assert set(d["categories"]) == {"Паспорт", "ИНН", "СНИЛС", "Загранпаспорт"}
    s1 = next(s for s in d["series"] if s["name"] == "t_ds.plan")
    s2 = next(s for s in d["series"] if s["name"] == "t_ds2.plan2")
    idx = {c: i for i, c in enumerate(d["categories"])}
    assert s1["data"][idx["Паспорт"]] == 100
    assert s1["data"][idx["Загранпаспорт"]] is None  # нет такой строки в t_ds
    assert s2["data"][idx["СНИЛС"]] is None  # нет такой строки в t_ds2
    assert s2["data"][idx["Паспорт"]] == 45


async def test_custom_labels(client, admin_headers, seed_dataset, seed_dataset2):
    r = await _preview(client, admin_headers, {
        "series": [
            {"dataset_code": "t_ds", "value_field": "plan", "label": "Первый"},
            {"dataset_code": "t_ds2", "value_field": "plan2", "label": "Второй"},
        ],
    })
    assert r.status_code == 200, r.text
    names = {s["name"] for s in r.json()["series"]}
    assert names == {"Первый", "Второй"}


async def test_period_match(client, admin_headers, seed_dataset, seed_dataset2):
    r = await _preview(client, admin_headers, {
        "match_by": "period",
        "series": [
            {"dataset_code": "t_ds", "value_field": "plan"},
            {"dataset_code": "t_ds2", "value_field": "plan2"},
        ],
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["match_by"] == "period"
    assert d["categories"] == ["2026-01-01", "2026-02-01"]
    s1 = next(s for s in d["series"] if s["name"] == "t_ds.plan")
    s2 = next(s for s in d["series"] if s["name"] == "t_ds2.plan2")
    assert s1["data"] == [165.0, 180.0]  # старый выпуск: (100-5)+(50-5)+(30-5); новый: 100+50+30
    assert s2["data"] == [65.0, 73.0]  # vals_old / vals_new суммы


async def test_requires_at_least_two_sources(client, admin_headers, seed_dataset):
    r = await _preview(client, admin_headers, {"series": [{"dataset_code": "t_ds", "value_field": "plan"}]})
    assert r.status_code == 400
    assert "минимум 2" in r.json()["detail"]


async def test_missing_field_in_item_400(client, admin_headers, seed_dataset, seed_dataset2):
    r = await _preview(client, admin_headers, {
        "series": [{"dataset_code": "t_ds", "value_field": "plan"}, {"dataset_code": "t_ds2"}],
    })
    assert r.status_code == 400


async def test_row_level_rls_filters_both_sources(client, admin_headers, viewer, seed_dataset, seed_dataset2):
    """t_ds и t_ds2 принадлежат РАЗНЫМ объектам (t_obj/t_obj2) — RLS применяется
    к каждому источнику независимо; правило нужно включить на обоих объектах,
    чтобы виджет сравнения источников ограничил строки в ОБОИХ рядах."""
    async with db.acquire() as conn:
        obj1 = str(await conn.fetchval("select id from objects where name='t_obj'"))
        obj2 = str(await conn.fetchval("select id from objects where name='t_obj2'"))
        org = await conn.fetchval("select organization_id from objects where id=$1::uuid", obj1)
        dep = str(await conn.fetchval(
            "insert into departments(organization_id,name) values($1,'ztest_dep_cross') returning id", org))
        await conn.execute("update users set department_id=$1::uuid where id=$2::uuid", dep, viewer["id"])

    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_cross_rls"})).json()["id"]
    try:
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "P"})).json()["id"]
        wid = (await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "X", "widget_type": "cross_dataset_compare",
            "config": {"series": [{"dataset_code": "t_ds", "value_field": "plan"},
                                   {"dataset_code": "t_ds2", "value_field": "plan2"}]},
        })).json()["id"]
        await client.post(f"/dashboards/{did}/grants", headers=admin_headers,
                          json={"grantee_type": "user", "user_id": viewer["id"]})
        await client.post(f"/dashboards/{did}/publish", headers=admin_headers)

        # без правил — видны все категории обоих источников
        d = (await client.get(f"/widgets/{wid}/data", headers=viewer["headers"])).json()
        assert set(d["categories"]) == {"Паспорт", "ИНН", "СНИЛС", "Загранпаспорт"}

        # включаем RLS на ОБОИХ объектах: отделу viewer разрешён только «Паспорт»
        r1 = await client.put(f"/objects/{obj1}/row-acl/{dep}", headers=admin_headers, json={"row_labels": ["Паспорт"]})
        r2 = await client.put(f"/objects/{obj2}/row-acl/{dep}", headers=admin_headers, json={"row_labels": ["Паспорт"]})
        assert r1.status_code == 200 and r2.status_code == 200

        d = (await client.get(f"/widgets/{wid}/data", headers=viewer["headers"])).json()
        assert set(d["categories"]) == {"Паспорт"}
        d_admin = (await client.get(f"/widgets/{wid}/data", headers=admin_headers)).json()
        assert set(d_admin["categories"]) == {"Паспорт", "ИНН", "СНИЛС", "Загранпаспорт"}  # привилегированный — без ограничений
    finally:
        await purge_dashboard(did)
        async with db.acquire() as conn:
            await conn.execute("delete from data_row_acl where object_id=any($1::uuid[])", [obj1, obj2])
            await conn.execute("update users set department_id=null where id=$1::uuid", viewer["id"])
            await conn.execute("delete from departments where name='ztest_dep_cross'")
