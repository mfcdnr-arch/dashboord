"""Порог показателя — один на графу формы (миграция 064, `dashboards/_norms`).

Держит три вещи: правка порога пересчитывает виджеты СРАЗУ (кэш сбрасывается);
итог «выше порога» считается по всем строкам, а не по показанным; свои пороги
виджета сильнее нормы графы.
"""
from __future__ import annotations

import pytest

from app import db
from app.modules.dashboards import _norms
from conftest import purge_dashboard

pytestmark = pytest.mark.asyncio(loop_scope="session")


def test_level_follows_direction():
    lower = {"warn": 20, "danger": 30, "direction": "lower"}
    assert [_norms.level(v, lower) for v in (10, 20, 29.9, 30, 365)] == ["good", "warn", "warn", "danger", "danger"]
    higher = {"warn": 90, "danger": 70, "direction": "higher"}
    assert [_norms.level(v, higher) for v in (95, 90, 71, 70)] == ["good", "warn", "warn", "danger"]
    assert _norms.level(None, lower) is None and _norms.level(5, None) is None
    assert _norms.describe(lower, "мин") == "внимание от 20 мин, проблема от 30 мин"


def test_norm_warnings_name_rows_with_durations():
    norms = {"wait": {"name": "Среднее время ожидания", "unit": "мин",
                      "norm": {"warn": None, "danger": 30, "direction": "lower"}}}
    values = {("Сартана", "wait"): 364.1, ("Енакиево", "wait"): 259.02, ("Донецк", "wait"): 7.0}
    (w,) = _norms.norm_warnings(values, norms)
    assert w["code"] == "norm_exceeded" and w["count"] == 2
    assert "у 2 строк из 3" in w["message"] and "Сартана — 6 ч 4 мин 6 с" in w["message"]


@pytest.fixture
async def wait_field(seed_dataset):
    """Графа `fact` формы t_ds — как длительность (минуты)."""
    async with db.acquire() as conn:
        obj = await conn.fetchval("select id from objects where name='t_obj'")
        await conn.execute(
            "insert into canonical_fields(object_id, code, name, data_type, unit) "
            "values($1,'fact','Среднее время ожидания','number','мин') "
            "on conflict (object_id, code) do update set unit='мин', norm=null, name=excluded.name", obj)
    yield
    async with db.acquire() as conn:
        await conn.execute("delete from canonical_fields where object_id=$1 and code='fact'", obj)
        await conn.execute("delete from audit_log where entity_type='field_norm'")


async def _widget(client, headers, wtype, cfg):
    did = (await client.post("/dashboards", headers=headers, json={"name": "ztest_norms"})).json()["id"]
    pid = (await client.post(f"/dashboards/{did}/pages", headers=headers, json={"name": "P"})).json()["id"]
    w = (await client.post(f"/dashboard-pages/{pid}/widgets", headers=headers,
                           json={"name": "W", "widget_type": wtype, "config": cfg})).json()
    return did, pid, w["id"]


async def test_setting_a_norm_recolors_widgets_at_once(client, admin_headers, wait_field):
    did, _pid, wid = await _widget(client, admin_headers, "ranked",
                                   {"dataset_code": "t_ds", "value_field": "fact", "top_n": 1, "unit": "мин"})
    try:
        before = (await client.get(f"/widgets/{wid}/data", headers=admin_headers)).json()
        # Без порога — строка «Порог: не задан» (длительность), но без окраски.
        assert before["norm_fields"][0]["norm"] is None and "norm_summary" not in before

        r = await client.put("/widgets/norms/t_ds/fact", headers=admin_headers, json={"warn": 30, "danger": 50})
        assert r.status_code == 200, r.text
        assert r.json()["text"] == "внимание от 30 мин, проблема от 50 мин"

        # Тот же запрос сразу после правки — без ожидания кэша. fact = 90, 55, 28.
        after = (await client.get(f"/widgets/{wid}/data", headers=admin_headers)).json()
        # top_n=1 показывает две строки из трёх, а итог — по ВСЕМ трём.
        assert after["norm_summary"] == "выше порога 50 мин: 2 · внимание (от 30 мин): 0 · в норме: 1"
        assert after["rows"][0]["norm_level"] == "danger"
    finally:
        await purge_dashboard(did)


async def test_kpi_gets_the_norm_unless_it_has_its_own_alerts(client, admin_headers, wait_field):
    await client.put("/widgets/norms/t_ds/fact", headers=admin_headers, json={"warn": None, "danger": 50})
    did, _pid, wid = await _widget(client, admin_headers, "kpi",
                                   {"dataset_code": "t_ds", "value_field": "fact", "agg": "sum", "unit": "мин"})
    try:
        d = (await client.get(f"/widgets/{wid}/data", headers=admin_headers)).json()
        assert d["alert"]["level"] == "danger" and d["alert"]["source"] == "norm"  # длительность усредняется: (90+55+28)/3 ≈ 57,7 мин
        # Свои пороги виджета сильнее нормы графы.
        await client.patch(f"/widgets/{wid}", headers=admin_headers, json={"config": {
            "dataset_code": "t_ds", "value_field": "fact", "agg": "sum", "unit": "мин",
            "alerts": [{"level": "good", "op": "gt", "value": 0, "label": "своё"}]}})
        d = (await client.get(f"/widgets/{wid}/data", headers=admin_headers)).json()
        assert d["alert"]["label"] == "своё"
    finally:
        await purge_dashboard(did)


async def test_norm_reaches_attention_and_validates(client, admin_headers, viewer, wait_field):
    bad = await client.put("/widgets/norms/t_ds/fact", headers=admin_headers, json={"warn": 60, "danger": 50})
    assert bad.status_code == 400 and "раньше" in bad.json()["detail"]
    assert (await client.put("/widgets/norms/t_ds/fact", headers=viewer["headers"],
                             json={"danger": 50})).status_code == 403
    await client.put("/widgets/norms/t_ds/fact", headers=admin_headers, json={"danger": 50})
    did, pid, _ = await _widget(client, admin_headers, "table", {"dataset_code": "t_ds"})
    try:
        att = (await client.get(f"/dashboard-pages/{pid}/attention", headers=admin_headers)).json()
        msgs = [w for it in att["items"] for w in it["warnings"] if w["code"] == "norm_exceeded"]
        assert msgs and msgs[0]["count"] == 2
        # Таблица красит только ячейки с превышением.
        tbl = (await client.get(f"/dashboard-pages/{pid}/data", headers=admin_headers)).json()["widgets"][0]["data"]
        marked = {r["row"]: r.get("__fmt", {}).get("fact") for r in tbl["rows"]}
        assert marked == {"Паспорт": "danger", "ИНН": "danger", "СНИЛС": None}
        # Снять порог — оба поля пусто.
        r = await client.put("/widgets/norms/t_ds/fact", headers=admin_headers, json={"warn": None, "danger": None})
        assert r.json()["norm"] is None
    finally:
        await purge_dashboard(did)


async def test_matrix_cells_carry_their_own_norm_level(client, admin_headers, wait_field):
    """Уровень порога лежит в САМОЙ строке матрицы: её сортируют кликом, и
    список по индексам красил бы чужие клетки."""
    await client.put("/widgets/norms/t_ds/fact", headers=admin_headers, json={"warn": 30, "danger": 50})
    r = await client.post("/widgets/preview", headers=admin_headers, json={
        "widget_type": "matrix", "name": "x", "config": {"dataset_code": "t_ds", "value_field": "fact", "unit": "мин"}})
    assert r.status_code == 200, r.text
    d = r.json()
    levels = {row["row"]: row["norm_levels"][-1] for row in d["rows"]}
    assert levels == {"Паспорт": "danger", "ИНН": "danger", "СНИЛС": "good"}  # 90, 55, 28 мин
    assert d["norm_summary"].startswith("в последнем отчёте — выше порога 50 мин: 2")


async def test_single_duration_field_widget_gets_its_unit(client, admin_headers, wait_field):
    """Виджет по одной графе времени, собранный без единицы, печатает минуты как время."""
    r = await client.post("/widgets/preview", headers=admin_headers, json={
        "widget_type": "matrix", "name": "x", "config": {"dataset_code": "t_ds", "value_field": "fact"}})
    assert r.json()["unit"] == "мин"
