"""🔴 Фильтр «Период» на странице действовал только на «Динамику» (п. 3).

Карточка, спидометр, таблица, графики, план-факт, воронка, светофор читали
ПОСЛЕДНИЙ выпуск и период игнорировали молча. Человек ставил июль, видел
августовские числа и либо решал, что данных нет, либо принимал их за июльские —
второе опаснее, потому что выглядит как рабочий ответ.

Здесь закрепляем новое правило: период выбирает ВЫПУСК (последний отчёт,
попавший в диапазон), а если отчётов за период нет — виджет говорит об этом, а
не подставляет свежие данные.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db


async def _dash(client, headers, name):
    did = (await client.post("/dashboards", headers=headers, json={"name": name})).json()["id"]
    pid = (await client.post(f"/dashboards/{did}/pages", headers=headers, json={"name": "Обзор"})).json()["id"]
    return did, pid


async def _drop(did):
    async with db.acquire() as conn:
        await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
        await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
        await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
        await conn.execute("delete from audit_log where entity_id=$1::uuid", did)
        await conn.execute("delete from dashboards where id=$1::uuid", did)


async def test_period_filter_picks_release_for_every_widget_type(client, admin_headers, seed_dataset):
    """Фикстура даёт два выпуска: 2026-01-01 (plan−5) и 2026-02-01 (plan+fact).

    Без фильтра карточка показывает февральскую сумму, с фильтром «январь» —
    январскую. Раньше оба ответа были одинаковыми.
    """
    did, pid = await _dash(client, admin_headers, "ztest_period_filter")
    try:
        ds = seed_dataset["code"]
        cfg = {"dataset_code": ds, "value_field": "plan"}
        kpi = (await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "ztest Карточка", "widget_type": "kpi", "config": cfg})).json()["id"]

        latest = (await client.get(f"/widgets/{kpi}/data", headers=admin_headers)).json()
        assert latest["value"] == float(seed_dataset["plan_sum"])
        assert latest["as_of"] == "2026-02-01"

        # Январь: тот же виджет обязан показать ЯНВАРСКИЕ числа (plan−5 на строку).
        jan = (await client.get(f"/widgets/{kpi}/data?from=2026-01-01&to=2026-01-31",
                                headers=admin_headers)).json()
        assert jan["value"] == float(seed_dataset["plan_sum"] - 5 * len(seed_dataset["rows"]))
        assert jan["as_of"] == "2026-01-01", "дата должна быть та, за которую данные реально показаны"
        assert jan["period_filtered"] is True
        assert jan["value"] != latest["value"], "фильтр периода обязан менять цифру"

        # Таблица и график — тот же выпуск, а не последний.
        for wtype in ("table", "bar"):
            wid = (await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
                "name": f"ztest {wtype}", "widget_type": wtype, "config": cfg})).json()["id"]
            d = (await client.get(f"/widgets/{wid}/data?from=2026-01-01&to=2026-01-31",
                                  headers=admin_headers)).json()
            assert d.get("as_of") == "2026-01-01", (wtype, d.get("as_of"))
    finally:
        await _drop(did)


async def test_period_without_reports_says_so_instead_of_showing_fresh(client, admin_headers, seed_dataset):
    """Отчётов за период нет — виджет молчит честно, а не показывает свежие."""
    did, pid = await _dash(client, admin_headers, "ztest_period_empty")
    try:
        kpi = (await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "ztest Карточка", "widget_type": "kpi",
            "config": {"dataset_code": seed_dataset["code"], "value_field": "plan"}})).json()["id"]
        d = (await client.get(f"/widgets/{kpi}/data?from=2020-01-01&to=2020-12-31",
                              headers=admin_headers)).json()
        assert d.get("no_data_in_period") is True
        assert "value" not in d, "цифры быть не должно вовсе — иначе её примут за значение за период"
    finally:
        await _drop(did)


async def test_dynamics_still_gets_the_whole_range(client, admin_headers, seed_dataset):
    """«Динамике» нужен весь ряд точек, а не один выпуск — её правило не менялось."""
    did, pid = await _dash(client, admin_headers, "ztest_period_dyn")
    try:
        wid = (await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "ztest Динамика", "widget_type": "dynamics",
            "config": {"dataset_code": seed_dataset["code"], "value_field": "plan"}})).json()["id"]

        full = (await client.get(f"/widgets/{wid}/data", headers=admin_headers)).json()
        assert len(full["periods"]) == 2

        # Диапазон, накрывающий оба отчёта, оставляет обе точки…
        both = (await client.get(f"/widgets/{wid}/data?from=2026-01-01&to=2026-02-28",
                                 headers=admin_headers)).json()
        assert len(both["periods"]) == 2
        # …а узкий диапазон обрезает ряд, а не подменяет его одной точкой из
        # другого месяца.
        one = (await client.get(f"/widgets/{wid}/data?from=2026-01-01&to=2026-01-31",
                                headers=admin_headers)).json()
        assert one["periods"] == ["2026-01-01"]
    finally:
        await _drop(did)


async def test_widget_own_filter_wins_over_page_period(client, admin_headers, seed_dataset):
    """Свой фильтр виджета перекрывает фильтр страницы — иначе виджет с
    собственным периодом получил бы чужой."""
    did, pid = await _dash(client, admin_headers, "ztest_period_own")
    try:
        wid = (await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "ztest Свой период", "widget_type": "kpi",
            "config": {"dataset_code": seed_dataset["code"], "value_field": "plan",
                       "filter_scope": "own", "own_from": "2026-01-01", "own_to": "2026-01-31"}})).json()["id"]
        # Страница просит февраль, у виджета свой январь — побеждает январь.
        d = (await client.get(f"/widgets/{wid}/data?from=2026-02-01&to=2026-02-28",
                              headers=admin_headers)).json()
        assert d["as_of"] == "2026-01-01"
    finally:
        await _drop(did)
