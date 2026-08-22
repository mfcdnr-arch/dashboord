"""Шаг ④ перестройки вида: матрица «строка × дата», индекс роста, прогноз плана.

Три ответа, которых на дашборде не было: как каждая СТРОКА двигалась от отчёта
к отчёту (матрица), насколько показатель вырос относительно старта независимо
от масштаба (индекс роста) и когда факт дорастёт до плана (прогноз).
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app.modules.dashboards._widgetcalc import _plan_forecast  # noqa: E402
from conftest import db, purge_dashboard  # noqa: E402


async def _widget(client, headers, page_id, name, wtype, cfg):
    r = await client.post(f"/dashboard-pages/{page_id}/widgets", headers=headers,
                          json={"name": name, "widget_type": wtype, "config": cfg})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_matrix_shows_every_row_across_reports(client, admin_headers, seed_dataset):
    """Матрица: строка × отчёт, в ячейке значение и прирост к прошлому отчёту."""
    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_matrix"})).json()["id"]
    try:
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "M"})).json()["id"]
        wid = await _widget(client, admin_headers, pid, "матрица", "matrix",
                            {"dataset_code": "t_ds", "value_field": "plan"})
        d = (await client.get(f"/widgets/{wid}/data", headers=admin_headers)).json()

        # Фикстура: старый выпуск (01.01) — plan−5, новый (01.02) — plan.
        assert d["periods"] == ["2026-01-01", "2026-02-01"]
        by_row = {r["row"]: r for r in d["rows"]}
        assert set(by_row) == {"Паспорт", "ИНН", "СНИЛС"}
        assert by_row["Паспорт"]["values"] == [95.0, 100.0]
        # Прирост считается к ПРЕДЫДУЩЕМУ отчёту той же строки, а не к соседней
        # строке и не к итогу — иначе матрица отвечала бы не на тот вопрос.
        assert by_row["Паспорт"]["deltas"][0] is None
        assert by_row["Паспорт"]["deltas"][1] == 5.0
        assert abs(by_row["Паспорт"]["delta_pcts"][1] - 5 / 95 * 100) < 0.01
        assert by_row["Паспорт"]["total_change"] == 5.0
        # Итог по столбцу — сумма строк за этот отчёт (то, что показывает «Динамика»).
        assert d["col_totals"] == [pytest.approx(95 + 45 + 25), pytest.approx(100 + 50 + 30)]
        assert d["total_periods"] == d["shown_periods"] == 2
        assert d["field_title"]  # человеческое имя показателя, а не код поля
    finally:
        await purge_dashboard(did)


async def test_matrix_keeps_only_last_reports(client, admin_headers, ids):
    """Недельная форма за год — полсотни столбцов; лишние отчёты отсекаются, но
    сколько их всего, виджет говорит честно."""
    async with db.acquire() as conn:
        obj = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,'ztest_matrix_obj') returning id", ids["org"])
        for i, per in enumerate(["2026-03-01", "2026-03-08", "2026-03-15", "2026-03-22"]):
            rel = await conn.fetchval(
                "insert into dataset_releases(organization_id,code,name,status,reporting_period_start,created_by,object_id) "
                "values($1,'ztest_matrix_ds','Матрица ДС','released',$2::text::date,$3,$4) returning id",
                ids["org"], per, ids["admin"], obj)
            await conn.execute(
                "insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,value_number) "
                "values($1,0,'Горловка','v',$2)", rel, 100 + i * 10)
    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_matrix2"})).json()["id"]
    try:
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "M"})).json()["id"]
        wid = await _widget(client, admin_headers, pid, "матрица", "matrix",
                            {"dataset_code": "ztest_matrix_ds", "value_field": "v", "max_periods": 2})
        d = (await client.get(f"/widgets/{wid}/data", headers=admin_headers)).json()
        assert d["shown_periods"] == 2 and d["total_periods"] == 4
        # Отсекаются СТАРЫЕ отчёты: смотрят всегда на свежие.
        assert d["periods"] == ["2026-03-15", "2026-03-22"]
        assert d["rows"][0]["values"] == [120.0, 130.0]
        # «За период» считается по показанному отрезку — ровно то, что видно.
        assert d["rows"][0]["total_change"] == 10.0
    finally:
        await purge_dashboard(did)
        async with db.acquire() as conn:
            await conn.execute("delete from dataset_values where dataset_release_id in "
                               "(select id from dataset_releases where code='ztest_matrix_ds')")
            await conn.execute("delete from dataset_releases where code='ztest_matrix_ds'")
            await conn.execute("delete from objects where name='ztest_matrix_obj' and organization_id=$1", ids["org"])


async def test_growth_index_starts_at_hundred(client, admin_headers, seed_dataset):
    """Индекс роста: первая точка = 100 %, абсолютные значения остаются рядом."""
    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_index"})).json()["id"]
    try:
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "D"})).json()["id"]
        wid = await _widget(client, admin_headers, pid, "динамика", "dynamics",
                            {"dataset_code": "t_ds", "value_field": "plan", "growth_index": True})
        d = (await client.get(f"/widgets/{wid}/data", headers=admin_headers)).json()
        assert d["index_values"][0] == 100.0
        assert d["index_values"][1] == pytest.approx(d["values"][1] / d["values"][0] * 100, abs=0.01)
        assert d["index_base_period"] == d["periods"][0]
        # Сами значения никуда не деваются: индекс — способ ПОКАЗА, а не замена
        # данных (иначе «сколько» ответить было бы негде).
        assert d["values"][0] == 165.0

        # Без галочки индекса нет — лишних полей в ответе не появляется.
        wid2 = await _widget(client, admin_headers, pid, "динамика-2", "dynamics",
                             {"dataset_code": "t_ds", "value_field": "plan"})
        d2 = (await client.get(f"/widgets/{wid2}/data", headers=admin_headers)).json()
        assert "index_values" not in d2
    finally:
        await purge_dashboard(did)


async def test_plan_forecast_is_honest_about_what_it_cannot_say():
    """Прогноз никогда не выдумывает дату: у каждого отказа своя причина."""
    series = [("2026-01-01", 50.0), ("2026-02-01", 100.0)]  # +50 за 31 день
    ok = _plan_forecast(series, plan=200.0, fact=100.0)
    assert ok["reason"] == "ok"
    assert ok["rate"] == pytest.approx(50 / 31)
    # Остаток 100 при темпе ~1,61/день — примерно 62 дня от последнего отчёта.
    assert ok["days"] == 62 and ok["date"] == "2026-04-04"
    assert ok["remain"] == 100.0 and ok["from_period"] == "2026-01-01"

    assert _plan_forecast(series, plan=100.0, fact=100.0)["reason"] == "done"
    assert _plan_forecast(series, plan=200.0, fact=None)["reason"] == "no_data"
    assert _plan_forecast(series[:1], plan=200.0, fact=100.0)["reason"] == "few_points"
    # Ряд не растёт — «никогда» честнее любой даты.
    flat = [("2026-01-01", 100.0), ("2026-02-01", 100.0)]
    assert _plan_forecast(flat, plan=200.0, fact=100.0)["reason"] == "no_growth"
    # Едва заметный рост: формально дата есть, но это «никогда» другими словами.
    crawl = [("2026-01-01", 100.0), ("2026-02-01", 100.1)]
    assert _plan_forecast(crawl, plan=10_000.0, fact=100.1)["reason"] == "too_far"


async def test_plan_fact_forecast_end_to_end(client, admin_headers, seed_dataset):
    """Прогноз на живом виджете: считается по галочке и только для сумм."""
    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_forecast"})).json()["id"]
    try:
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "PF"})).json()["id"]
        cfg = {"dataset_code": "t_ds", "plan_field": "plan", "fact_field": "fact"}
        plain = await _widget(client, admin_headers, pid, "план-факт", "plan_fact", cfg)
        assert "forecast" not in (await client.get(f"/widgets/{plain}/data", headers=admin_headers)).json()

        wid = await _widget(client, admin_headers, pid, "план-факт+прогноз", "plan_fact", {**cfg, "forecast": True})
        d = (await client.get(f"/widgets/{wid}/data", headers=admin_headers)).json()
        # Факт (173) меньше плана (180), но ряд `fact` есть только в последнем
        # выпуске — сравнивать не с чем, и виджет об этом говорит прямо.
        assert d["forecast"]["reason"] in {"few_points", "ok", "no_growth"}

        # По полю `plan` ряд из двух отчётов есть — прогноз считается.
        wid2 = await _widget(client, admin_headers, pid, "план-факт-2", "plan_fact",
                             {"dataset_code": "t_ds", "plan_field": "fact", "fact_field": "plan", "forecast": True})
        d2 = (await client.get(f"/widgets/{wid2}/data", headers=admin_headers)).json()
        # План (fact=173) уже перекрыт фактом (plan=180) → «выполнено».
        assert d2["forecast"]["reason"] == "done"
    finally:
        await purge_dashboard(did)
