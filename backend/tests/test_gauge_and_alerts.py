"""Спидометр для процентов и цветовые пороги «нормы» в авто-сборке.

Голое «187 %» и голое «64 %» на дашборде выглядят одинаково спокойно, хотя
означают противоположное. Две правки, обе — правила, не ИИ:

(1) процентный показатель показывается спидометром: на шкале сразу видно,
    близко ли к 100 %;
(2) выполнению плана проставляются пороги — ниже 90 % красный, ниже 100 %
    жёлтый, от 100 % зелёный. Норма здесь не выдумана: 100 % — это сам план.
    Показателям без известной нормы (доля доставленных) пороги НЕ ставятся:
    выдуманное правило, покрашенное красным, хуже отсутствующего.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from app.modules.dashboards import _suggest
from app.modules.dashboards._widgetcalc import _nice_ceiling


def _fields():
    """Пара «план + факт» в виде имён госформы: «Показатель · Роль · Разрез»."""
    return [
        {"code": "plan", "name": "Количество услуг · План · нарастающим итогом"},
        {"code": "fact", "name": "Количество услуг · Факт · нарастающим итогом"},
    ]


def test_plan_fact_gets_thresholds_and_switch_turns_them_off():
    """Полоса «план и факт» краснеет ниже нормы, но галочку можно снять."""
    ds = [{"code": "t", "name": "Форма", "periods": 2, "releases": 2,
           "fields": _fields(), "period_dates": []}]

    on = [s for s in _suggest.plan_auto_build(ds, None) if s["widget_type"] == "plan_fact"]
    assert on, "пара план+факт должна дать полосу выполнения"
    rules = on[0]["config"]["alerts"]
    # Порядок правил важен: сработает ПЕРВОЕ подошедшее, поэтому danger раньше warn.
    assert [r["level"] for r in rules] == ["danger", "warn", "good"]
    assert rules[0]["value"] == 90 and rules[1]["value"] == 100

    off = [s for s in _suggest.plan_auto_build(ds, None, alerts=False)
           if s["widget_type"] == "plan_fact"]
    assert off and "alerts" not in off[0]["config"], "галочка должна выключать пороги"


def test_only_plan_execution_gets_a_norm():
    """Спидометр — всем процентам, пороги — только выполнению плана."""
    wt, cfg = _suggest.metric_widget_spec("%", plan_execution=True)
    assert wt == "gauge" and cfg["alerts"], "у процента выполнения норма известна"

    wt, cfg = _suggest.metric_widget_spec("%", plan_execution=False)
    assert wt == "gauge" and cfg == {}, \
        "у доли нормы нет — раскрасить её значило бы выдать выдумку за правило"

    wt, cfg = _suggest.metric_widget_spec(None, plan_execution=False)
    assert wt == "kpi" and cfg == {}, "не-процент остаётся карточкой"


def test_gauge_scale_grows_past_hundred():
    """Перевыполнение не должно упираться в край шкалы.

    У заказчика выполнение плана доходит до 656 %: при жёстком потолке 100
    стрелка стояла бы на пределе и выглядела бы как «ровно 100 %».
    """
    assert _nice_ceiling(100 * 1.1) == 150
    assert _nice_ceiling(187 * 1.1) == 250
    assert _nice_ceiling(656 * 1.1) == 750
    assert _nice_ceiling(0) == 100, "нулевое значение не должно давать нулевую шкалу"


async def test_percent_gauge_widget_scales_to_its_value(client, admin_headers, seed_dataset):
    """Сквозь весь расчёт: недобор жёлтый на шкале 100, перебор расширяет шкалу."""
    ds = seed_dataset["code"]
    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_gauge_scale"})
    did = r.json()["id"]
    pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                             json={"name": "Стр"})).json()["id"]

    async def gauge(name, plan_field, fact_field):
        r = await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": name, "widget_type": "gauge", "width": 4, "height": 6,
            "config": {"formula": f"PLAN_FACT_PCT(SUM(field('{ds}','{plan_field}')), "
                                  f"SUM(field('{ds}','{fact_field}')))",
                       "unit": "%", "alerts": [dict(x) for x in _suggest.PLAN_PCT_ALERTS]}})
        assert r.status_code == 201, r.text
        return (await client.get(f"/widgets/{r.json()['id']}/data", headers=admin_headers)).json()

    try:
        # План 180, факт 173 → 96,1 %: план не выполнен, шкала обычная.
        under = await gauge("ztest недобор", "plan", "fact")
        assert under["value"] < 100 and under["max"] == 100
        assert under["alert"]["level"] == "warn", under["alert"]

        # Меняем поля местами: 180 от 173 → 104 % — перевыполнение.
        over = await gauge("ztest перебор", "fact", "plan")
        assert over["value"] > 100
        assert over["max"] > over["value"], "стрелка не должна упираться в край шкалы"
        assert over["alert"]["level"] == "good", over["alert"]
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
            await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)


async def test_placed_percent_metric_becomes_gauge_with_norm(client, admin_headers, seed_dataset):
    """Кнопка «Разместить на дашборде»: процент выполнения → спидометр с порогами.

    Вид и пороги выводятся из САМОЙ формулы показателя (PLAN_FACT_PCT в AST) —
    человек не обязан помнить, из чего его показатель считается.
    """
    ds = seed_dataset["code"]
    r = await client.post("/metrics", headers=admin_headers, json={
        "code": "ztest_gauge_exec", "name": "ztest выполнение плана, %"})
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    await client.post(f"/metrics/{mid}/versions", headers=admin_headers, json={
        "formula": f"PLAN_FACT_PCT(SUM(field('{ds}','plan')), SUM(field('{ds}','fact')))",
        "unit": "%"})

    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_gauge_place"})
    did = r.json()["id"]
    pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                             json={"name": "Обзор"})).json()["id"]
    try:
        r = await client.post("/dashboards/place-metric", headers=admin_headers, json={
            "page_id": pid, "metric_code": "ztest_gauge_exec",
            "name": "ztest выполнение плана, %", "unit": "%"})
        assert r.status_code == 201, r.text
        async with db.acquire() as conn:
            row = await conn.fetchrow(
                "select widget_type, config::text as cfg, height from widgets where id=$1::uuid",
                r.json()["widget_id"])
        assert row["widget_type"] == "gauge", "процент читается на шкале, а не голым числом"
        assert '"alerts"' in row["cfg"], "у выполнения плана норма известна — пороги ставим"
        assert row["height"] >= 7, "шкале нужна карточка выше обычной"
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
            await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)
            await conn.execute("delete from metric_versions where metric_id=$1::uuid", mid)
            await conn.execute("delete from metrics where id=$1::uuid", mid)


async def test_placed_share_metric_has_no_invented_norm(client, admin_headers, seed_dataset):
    """Доля — тоже спидометр, но БЕЗ порогов: нормы у неё нет."""
    ds = seed_dataset["code"]
    r = await client.post("/metrics", headers=admin_headers, json={
        "code": "ztest_gauge_share", "name": "ztest доля, %"})
    mid = r.json()["id"]
    await client.post(f"/metrics/{mid}/versions", headers=admin_headers, json={
        "formula": f"PERCENT_OF(SUM(field('{ds}','plan')), SUM(field('{ds}','fact')))",
        "unit": "%"})

    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_share_place"})
    did = r.json()["id"]
    pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                             json={"name": "Обзор"})).json()["id"]
    try:
        r = await client.post("/dashboards/place-metric", headers=admin_headers, json={
            "page_id": pid, "metric_code": "ztest_gauge_share", "name": "ztest доля, %", "unit": "%"})
        async with db.acquire() as conn:
            row = await conn.fetchrow(
                "select widget_type, config::text as cfg from widgets where id=$1::uuid",
                r.json()["widget_id"])
        assert row["widget_type"] == "gauge"
        assert '"alerts"' not in row["cfg"], "у доли нормы нет — порогов быть не должно"
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
            await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)
            await conn.execute("delete from metric_versions where metric_id=$1::uuid", mid)
            await conn.execute("delete from metrics where id=$1::uuid", mid)


def test_metric_cards_of_different_height_do_not_overlap():
    """Спидометры и карточки лежат отдельными пачками — иначе наложатся.

    Высота ряда считается по номеру ряда, поэтому виджет высотой 6 в ряду
    высотой 5 залез бы на следующий ряд.
    """
    gauges = [{"code": f"g{i}"} for i in range(4)]
    cards = [{"code": f"c{i}"} for i in range(2)]
    boxes = []
    y = 0
    for _item, pos in _suggest._grid_rows(gauges, y, per_row=3, width=4, height=7):
        boxes.append(pos)
    y += _suggest._rows_height(len(gauges), 3, 7)
    for _item, pos in _suggest._grid_rows(cards, y, per_row=3, width=4, height=5):
        boxes.append(pos)

    for i, a in enumerate(boxes):
        assert a["position_x"] + a["width"] <= 12, a
        for b in boxes[i + 1:]:
            overlap = (a["position_x"] < b["position_x"] + b["width"]
                       and b["position_x"] < a["position_x"] + a["width"]
                       and a["position_y"] < b["position_y"] + b["height"]
                       and b["position_y"] < a["position_y"] + a["height"])
            assert not overlap, (a, b)
