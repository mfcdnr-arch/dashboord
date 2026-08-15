"""Мастер, этап 3: отдельные страницы по отчётным периодам.

Заказчику нужны ОБА варианта: сводный дашборд, который обновляется сам, и
страницы за конкретные недели. Разница принципиальная и легко теряется:
у сводной страницы виджет читает ПОСЛЕДНИЙ выпуск, у страницы-среза — выпуск
за закреплённую дату, и приход новой недели её не меняет. Здесь проверяется
именно это, а не только наличие страниц.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from app.modules.dashboards import _suggest


def _dataset(periods):
    return [{
        "code": "t_ds", "name": "Форма", "periods": len(periods), "releases": len(periods),
        "fields": [{"code": "plan", "name": "План"}, {"code": "fact", "name": "Факт"}],
        "period_dates": periods,
    }]


def test_period_pages_only_by_explicit_choice():
    """Молча 15 страниц не собираем — дашборд стало бы невозможно открыть."""
    ds = _dataset(["2026-08-05", "2026-07-29", "2026-07-22"])
    specs = _suggest.plan_auto_build(ds, None)
    assert not [s for s in specs if s["page"].startswith(_suggest.PAGE_PERIOD_PREFIX)]

    sel = {"t_ds": {"fields": ["plan", "fact"], "blocks": list(_suggest.BLOCKS),
                    "views": {}, "periods": ["2026-07-29"]}}
    specs = _suggest.plan_auto_build(ds, sel)
    pages = {s["page"] for s in specs if s["page"].startswith(_suggest.PAGE_PERIOD_PREFIX)}
    assert pages == {"Отчёт за 29.07.2026"}, pages


def test_period_widgets_are_pinned_to_that_date():
    """У виджета страницы-среза закреплена дата, у сводного — нет.

    Без этого страница «за 29.07» показывала бы данные последней недели, то
    есть врала бы заголовком.
    """
    ds = _dataset(["2026-08-05", "2026-07-29"])
    sel = {"t_ds": {"fields": ["plan"], "blocks": list(_suggest.BLOCKS),
                    "views": {}, "periods": ["2026-07-29"]}}
    specs = _suggest.plan_auto_build(ds, sel)
    period_specs = [s for s in specs if s["page"].startswith(_suggest.PAGE_PERIOD_PREFIX)]
    summary_specs = [s for s in specs if not s["page"].startswith(_suggest.PAGE_PERIOD_PREFIX)]

    assert period_specs, specs
    assert all(s["config"].get("period") == "2026-07-29" for s in period_specs)
    assert all("period" not in s["config"] for s in summary_specs), "сводные страницы не закрепляются"


def test_unknown_and_extra_periods_are_ignored():
    """Дата, которой нет в данных, страницу не создаёт; число страниц ограничено."""
    dates = [f"2026-0{m}-0{d}" for m in (4, 5) for d in range(1, 8)]
    ds = _dataset(dates)
    sel = {"t_ds": {"fields": ["plan"], "blocks": list(_suggest.BLOCKS), "views": {},
                    "periods": [*dates, "1999-01-01"]}}
    specs = _suggest.plan_auto_build(ds, sel)
    pages = {s["page"] for s in specs if s["page"].startswith(_suggest.PAGE_PERIOD_PREFIX)}
    assert "Отчёт за 01.01.1999" not in pages
    assert len(pages) == _suggest.MAX_AUTO_PERIOD_PAGES


async def test_pinned_widget_reads_its_own_period(client, admin_headers, seed_dataset):
    """Сквозная проверка: закреплённый виджет считает данные СВОЕЙ недели.

    Фикстура даёт два выпуска: 01.01 (plan −5 у каждой строки) и 02.01 (plan
    как есть). Виджет без периода должен показать свежий выпуск, с периодом —
    старый.
    """
    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_period_dash"})
    did = r.json()["id"]
    r = await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "Стр"})
    pid = r.json()["id"]
    try:
        latest = await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "Сводный", "widget_type": "kpi",
            "config": {"dataset_code": seed_dataset["code"], "value_field": "plan"}})
        pinned = await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "За 01.01", "widget_type": "kpi",
            "config": {"dataset_code": seed_dataset["code"], "value_field": "plan",
                       "period": "2026-01-01"}})

        a = (await client.get(f"/widgets/{latest.json()['id']}/data", headers=admin_headers)).json()
        b = (await client.get(f"/widgets/{pinned.json()['id']}/data", headers=admin_headers)).json()

        assert a["value"] == seed_dataset["plan_sum"], a
        # Старый выпуск: у каждой строки на 5 меньше.
        assert b["value"] == seed_dataset["plan_sum"] - 5 * len(seed_dataset["rows"]), b
        assert b["as_of"] == "2026-01-01", "подпись свежести должна называть закреплённую дату"
        assert b.get("period_locked") is True, "страница-срез обязана честно говорить, что не обновляется"
        assert a.get("period_locked") is None
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
            await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)
