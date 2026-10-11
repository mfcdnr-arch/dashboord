"""Показатели между формами (`dashboards/_crossform`).

Главное правило — ОТНОШЕНИЕ СУММ, а не среднее частных: у отделения с одним
окном и отделения с пятнадцатью окнами «талонов на окно» весят по-разному.
И строка, которой нет в одной из форм, не входит в расчёт и называется.
"""
from __future__ import annotations

import pytest

from app import db
from conftest import purge_dashboard

pytestmark = pytest.mark.asyncio(loop_scope="session")

A, B = "ztest_cross_tickets", "ztest_cross_windows"

# Отделение «Большое»: 300 талонов на 15 окон (20 на окно); «Малое»: 30 на 1
# окно (30 на окно). Среднее частных — 25, отношение сумм — 330 / 16 = 20,625.
# «Только в талонах» в форме окон отсутствует — в расчёт не входит.
TICKETS = {"2026-03-01": {"Большое": 300, "Малое": 30, "Только в талонах": 999},
           "2026-03-02": {"Большое": 150, "Малое": 10}}
WINDOWS = {"2026-03-01": {"Большое": 15, "Малое": 1},
           "2026-03-02": {"Большое": 15, "Малое": 1}}
WAIT = {"2026-03-01": {"Большое": 10.0, "Малое": 40.0}}


@pytest.fixture
async def two_forms(ids, seed_dataset):
    async with db.acquire() as conn:
        obj = await conn.fetchval("select id from objects where name='t_obj'")
        await _drop(conn)
        for code, table, fields in ((A, TICKETS, "tickets"), (B, WINDOWS, "windows")):
            for day, rows in table.items():
                rel = await conn.fetchval(
                    "insert into dataset_releases(organization_id,code,name,status,reporting_period_start,"
                    "created_by,object_id) values($1,$2,'x','released',$3::text::date,$4,$5) returning id",
                    ids["org"], code, day, ids["admin"], obj)
                for i, (label, v) in enumerate(rows.items()):
                    await conn.execute(
                        "insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,"
                        "value_number) values($1,$2,$3,$4,$5)", rel, i, label, fields, v)
                    if code == A and label in WAIT.get(day, {}):
                        await conn.execute(
                            "insert into dataset_values(dataset_release_id,row_index,row_label,"
                            "canonical_field_code,value_number) values($1,$2,$3,'wait',$4)",
                            rel, i, label, WAIT[day][label])
    yield
    async with db.acquire() as conn:
        await _drop(conn)


async def _drop(conn):
    await conn.execute("delete from dataset_values where dataset_release_id in "
                       "(select id from dataset_releases where code = any($1::text[]))", [A, B])
    await conn.execute("delete from dataset_releases where code = any($1::text[])", [A, B])


def _cross(num, den, unit=None):
    return {"dataset_code": A, "value_field": num[0][1],
            "cross": {"num": [{"dataset_code": c, "field": f} for c, f in num],
                      "den": [{"dataset_code": c, "field": f} for c, f in den], "unit": unit}}


async def _preview(client, headers, wtype, cfg, **params):
    r = await client.post("/widgets/preview", headers=headers,
                          json={"widget_type": wtype, "name": "x", "config": cfg})
    assert r.status_code == 200, r.text
    return r.json()


async def test_ratio_of_sums_not_mean_of_ratios(client, admin_headers, two_forms):
    cfg = _cross([(A, "tickets")], [(B, "windows")])
    k = await _preview(client, admin_headers, "kpi", cfg)
    # Последний общий день — 02.03: (150 + 10) / (15 + 1) = 10.
    assert k["value"] == pytest.approx(10.0) and k["as_of"] == "2026-03-02"
    assert k["prev_value"] == pytest.approx(330 / 16)  # не 25 — не среднее частных
    assert "2 отделения" in k["cross_note"]

    dyn = await _preview(client, admin_headers, "dynamics", cfg)
    assert dyn["periods"] == ["2026-03-01", "2026-03-02"]
    assert dyn["values"] == [pytest.approx(330 / 16), pytest.approx(10.0)]


async def test_ranked_names_rows_missing_from_one_form(client, admin_headers, two_forms):
    cfg = {**_cross([(A, "tickets")], [(B, "windows")])}
    r = await _preview(client, admin_headers, "ranked", {**cfg, "own_from": None})
    # Последний общий день — 02.03: у обоих по 10 на окно.
    assert {x["label"]: x["value"] for x in r["rows"]} == {"Большое": pytest.approx(10.0), "Малое": pytest.approx(10.0)}
    # С периодом — сумма по дням периода у каждой строки.
    r = await client.post("/widgets/preview", headers=admin_headers, json={
        "widget_type": "ranked", "name": "x",
        "config": {**cfg, "filter_scope": "own", "own_from": "2026-03-01", "own_to": "2026-03-01"}})
    rows = {x["label"]: x["value"] for x in r.json()["rows"]}
    assert rows == {"Большое": pytest.approx(20.0), "Малое": pytest.approx(30.0)}
    assert "1 отделение есть не во всех формах" in r.json()["cross_note"]


async def test_weighted_average_counts_flow(client, admin_headers, two_forms):
    """Σ(ожидание × талоны) ÷ Σ талоны: у большого потока голос больше.
    (10×300 + 40×30) / 330 = 12,727…, а простое среднее было бы 25."""
    cfg = _cross([(A, "wait"), (A, "tickets")], [(A, "tickets")], unit="мин")
    k = await _preview(client, admin_headers, "kpi", cfg)
    assert k["value"] == pytest.approx((10 * 300 + 40 * 30) / 330) and k["unit"] == "мин"


async def test_cross_page_needs_matching_fields(client, admin_headers):
    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_cross_page"})).json()["id"]
    try:
        plan = (await client.get(f"/dashboards/{did}/cross-page/plan", headers=admin_headers)).json()
        if not plan["indicators"]:
            r = await client.post(f"/dashboards/{did}/cross-page", headers=admin_headers)
            assert r.status_code == 400 and "нет форм" in r.json()["detail"]
    finally:
        await purge_dashboard(did)
