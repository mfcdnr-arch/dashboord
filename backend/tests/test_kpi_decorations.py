"""Карточка KPI: прирост к прошлому отчёту и мини-график.

Одно число не отвечает на вопрос «много это или мало» — а «+38 174 (+4,3 %) к
прошлому отчёту» отвечает. Оба украшения стоят дополнительного запроса, поэтому
включаются галочкой, а не всегда: на странице карточек бывает полтора десятка.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db


async def _widget(client, headers, page_id, cfg, name="ztest kpi"):
    r = await client.post(f"/dashboard-pages/{page_id}/widgets", headers=headers, json={
        "name": name, "widget_type": "kpi", "config": cfg})
    return r.json()["id"]


async def test_kpi_delta_and_spark_are_opt_in(client, admin_headers, seed_dataset):
    """Без галочек карточка отдаёт только число; с ними — прирост и ряд."""
    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_kpi_deco"})
    did = r.json()["id"]
    r = await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "Стр"})
    pid = r.json()["id"]
    try:
        plain = await _widget(client, admin_headers, pid, {
            "dataset_code": seed_dataset["code"], "value_field": "plan"})
        rich = await _widget(client, admin_headers, pid, {
            "dataset_code": seed_dataset["code"], "value_field": "plan",
            "compare_prev": True, "spark": True}, name="ztest kpi rich")

        a = (await client.get(f"/widgets/{plain}/data", headers=admin_headers)).json()
        assert a["value"] == seed_dataset["plan_sum"]
        assert "prev_value" not in a and "spark" not in a, "по умолчанию лишних запросов не делаем"

        b = (await client.get(f"/widgets/{rich}/data", headers=admin_headers)).json()
        # Фикстура: старый выпуск на 5 меньше по каждой из трёх строк.
        assert b["prev_value"] == seed_dataset["plan_sum"] - 5 * len(seed_dataset["rows"])
        assert b["delta"] == 15 and b["delta_pct"] is not None
        assert b["prev_period"], "дата прошлого отчёта нужна для подсказки"
        assert len(b["spark"]) == 2, "мини-график строится по всем периодам"
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
            await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)


def test_planner_enables_delta_only_when_there_is_something_to_compare():
    """Планировщик включает прирост, только когда периодов больше одного."""
    from app.modules.dashboards import _suggest

    def cards(periods: int) -> list:
        ds = [{"code": "t", "name": "Ф", "periods": periods, "releases": periods,
               "fields": [{"code": "a", "name": "Показатель"}], "period_dates": []}]
        specs = _suggest.plan_auto_build(ds, None)
        return [s for s in specs if s["widget_type"] == "kpi"]

    one = cards(1)
    many = cards(3)
    assert one and all("compare_prev" not in c["config"] for c in one), \
        "с одним отчётом сравнивать не с чем — лишний запрос не делаем"
    assert many and all(c["config"].get("compare_prev") for c in many)
