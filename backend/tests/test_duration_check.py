"""Проверка качества «время больше N часов» (12.10.2026).

Случай заказчика: форма «Время» за 08.09 — Сартана 6 ч 4 мин ожидания,
Енакиево 4 ч 19 мин при обычных 15–25 минутах. Почти наверняка сбой учёта;
такой день должен уходить человеку, а не на дашборд сам. Порог — в
«Настройках», 0 выключает проверку.
"""
from __future__ import annotations

import pytest

from app import db
from app.modules.ingestion import quality

pytestmark = pytest.mark.asyncio(loop_scope="session")

UNITS = {"wait": "мин", "tickets": None}
NAMES = {"wait": "Среднее время ожидания", "tickets": "Талонов"}
VALUES = {("Сартана", "wait"): 364.1, ("Енакиево", "wait"): 259.0, ("Донецк", "wait"): 21.0,
          ("Сартана", "tickets"): 900.0}  # 900 талонов — не время, не трогаем


def _codes(found):
    return [w["code"] for w in found]


def test_long_duration_is_named_with_rows():
    found = quality.check_release(VALUES, NAMES, units=UNITS, duration_limit_hours=3)
    (w,) = [x for x in found if x["code"] == "duration_too_long"]
    assert w["count"] == 2
    assert "Время больше 3 ч у 2 строк" in w["message"]
    assert "Сартана — 6 ч 4 мин 6 с" in w["message"] and "Енакиево — 4 ч 19 мин" in w["message"]
    assert "Донецк" not in w["message"]


def test_zero_or_missing_units_turn_the_check_off():
    assert "duration_too_long" not in _codes(quality.check_release(VALUES, NAMES, units=UNITS, duration_limit_hours=0))
    assert "duration_too_long" not in _codes(quality.check_release(VALUES, NAMES, duration_limit_hours=3))
    # Единственная строка — 1 «строки», а не «строк».
    one = quality.check_release({("Сартана", "wait"): 364.1}, NAMES, units=UNITS, duration_limit_hours=5)
    assert "у 1 строки" in one[0]["message"]


@pytest.fixture
async def wait_unit(seed_dataset):
    async with db.acquire() as conn:
        obj = await conn.fetchval("select id from objects where name='t_obj'")
        await conn.execute(
            "insert into canonical_fields(object_id, code, name, data_type, unit) "
            "values($1,'fact','Среднее время ожидания','number','мин') "
            "on conflict (object_id, code) do update set unit='мин', norm=null, name=excluded.name", obj)
    yield obj
    async with db.acquire() as conn:
        await conn.execute("delete from canonical_fields where object_id=$1 and code='fact'", obj)


async def test_duration_context_reads_units_and_setting(ids, wait_unit, client, admin_headers):
    async with db.acquire() as conn:
        units, limit = await quality.duration_context(conn, ids["org"], "t_ds")
    assert units.get("fact") == "мин" and limit == 3  # умолчание
    before = (await client.get("/system/settings", headers=admin_headers)).json()["org"]
    try:
        r = await client.put("/system/settings/org", headers=admin_headers, json={"duration_limit_hours": 1.25})
        assert r.status_code == 200 and r.json()["duration_limit_hours"] == 1.25
        async with db.acquire() as conn:
            _u, limit = await quality.duration_context(conn, ids["org"], "t_ds")
        assert limit == 1.25
        # Блок «На что посмотреть» видит ту же проверку: fact = 90, 55, 28 мин.
        did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_duration"})).json()["id"]
        try:
            pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "P"})).json()["id"]
            await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                              json={"name": "W", "widget_type": "table", "config": {"dataset_code": "t_ds"}})
            att = (await client.get(f"/dashboard-pages/{pid}/attention", headers=admin_headers)).json()
            hits = [w for it in att["items"] for w in it["warnings"] if w["code"] == "duration_too_long"]
            assert hits and hits[0]["count"] == 1  # только 90 мин > 1 ч 15 мин
        finally:
            from conftest import purge_dashboard
            await purge_dashboard(did)
        bad = await client.put("/system/settings/org", headers=admin_headers, json={"duration_limit_hours": -1})
        assert bad.status_code == 422
    finally:
        await client.put("/system/settings/org", headers=admin_headers,
                         json={"duration_limit_hours": before.get("duration_limit_hours", 3)})


async def test_norms_list_for_settings(client, admin_headers, viewer, wait_unit):
    r = await client.get("/widgets/norms", headers=admin_headers)
    assert r.status_code == 200
    item = next(x for x in r.json()["items"] if x["dataset_code"] == "t_ds" and x["field"] == "fact")
    assert item["norm"] is None and item["direction"] == "lower" and item["object_name"] == "t_obj"
    assert (await client.get("/widgets/norms", headers=viewer["headers"])).status_code == 403


def test_count_without_slice_word_is_not_a_running_total():
    """Ежедневная форма «Время»: «Всего выдано талонов» законно уменьшается от
    дня ко дню. До 12.10.2026 графа без слова о разрезе считалась нарастающим
    итогом, и замечание «накопительный итог уменьшился» стояло в 17 днях из 20
    — каждое останавливало бы авто-выпуск."""
    assert quality.classify_slice("Всего выдано талонов (жив. и пред.)") == "other"
    assert quality.classify_slice("Количество обращений · нарастающим итогом") == "cumulative"
    assert quality.classify_slice("Принято накопительным итогом") == "cumulative"
    prev = {("Ялта", "t"): 22.0}
    cur = {("Ялта", "t"): 5.0}
    found = quality.compare_with_previous(cur, prev, {"t": "Всего выдано талонов (жив. и пред.)"})
    assert "cumulative_drop" not in [w["code"] for w in found]
