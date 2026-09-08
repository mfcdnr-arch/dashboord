"""Матрица по МЕСЯЦАМ: как отчёты сворачиваются в месяц и что об этом сказано.

У ежедневного отчёта РЦО 53 выпуска за два месяца, и матрица «строка × отчётная
дата» показывает последние 12 дней: она отвечает на «что было на прошлой
неделе», но не на «как прошёл месяц». Здесь проверяется вторая половина — и
главное в ней не сама группировка, а ПРАВИЛО СВЁРТКИ: накопительный итог,
сложенный по отчётам месяца, даёт число, которого не существует.

Числа взяты настоящие: три августовских отчёта формы МАХ по графе
«нарастающим итогом» — 876 479, 911 538 и 943 442.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from app.modules.dashboards._widgetcalc import fold_of

CODE = "zmm_ds"

# Три графы разного рода — ровно то, что лежит в одной форме рядом.
FIELDS = {
    "flow": "ИТОГО · Принято, ед.",
    "cum": "Количество доставленных · Факт · нарастающим итогом",
    "share": "Доля доставленных, %",
}
# Июль — три отчёта, август — два: месяцы НЕРАВНЫ, и виджет обязан об этом сказать.
RELEASES = {
    "2026-07-05": {"flow": 100.0, "cum": 1000.0, "share": 30.0},
    "2026-07-12": {"flow": 200.0, "cum": 1200.0, "share": 40.0},
    "2026-07-19": {"flow": 300.0, "cum": 1500.0, "share": 50.0},
    "2026-08-02": {"flow": 400.0, "cum": 1800.0, "share": 60.0},
    "2026-08-09": {"flow": 500.0, "cum": 2000.0, "share": 80.0},
}


@pytest.fixture
async def mm_ds(ids):
    async with db.acquire() as conn:
        await conn.execute("delete from dataset_values where dataset_release_id in "
                           "(select id from dataset_releases where code=$1)", CODE)
        await conn.execute("delete from dataset_releases where code=$1", CODE)
        await conn.execute("delete from objects where name=$1 and organization_id=$2",
                           "zmm_obj", ids["org"])
        obj = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,'zmm_obj') returning id", ids["org"])
        for code, nm in FIELDS.items():
            await conn.execute("insert into canonical_fields(object_id,code,name,data_type) "
                               "values($1,$2,$3,'number')", obj, code, nm)
        for period, vals in RELEASES.items():
            rel = await conn.fetchval(
                "insert into dataset_releases(organization_id,code,name,status,"
                "reporting_period_start,created_by,object_id) "
                "values($1,$2,'Месяцы',$3,$4::text::date,$5,$6) returning id",
                ids["org"], CODE, "released", period, ids["admin"], obj)
            for code, v in vals.items():
                await conn.execute("insert into dataset_release_fields(dataset_release_id,"
                                   "canonical_field_code) values($1,$2)", rel, code)
                # Две строки-отделения: свёртка строк и свёртка месяцев — разные
                # вещи, и путать их нельзя.
                for ri, (label, k) in enumerate((("Горловка", 0.6), ("Донецк", 0.4))):
                    await conn.execute(
                        "insert into dataset_values(dataset_release_id,row_index,row_label,"
                        "canonical_field_code,value_number) values($1,$2,$3,$4,$5)",
                        rel, ri, label, code, v * k)
    yield CODE
    async with db.acquire() as conn:
        await conn.execute("delete from dataset_values where dataset_release_id in "
                           "(select id from dataset_releases where code=$1)", CODE)
        await conn.execute("delete from dataset_release_fields where dataset_release_id in "
                           "(select id from dataset_releases where code=$1)", CODE)
        await conn.execute("delete from dataset_releases where code=$1", CODE)
        await conn.execute("delete from canonical_fields where object_id in "
                           "(select id from objects where name='zmm_obj')")
        await conn.execute("delete from objects where name='zmm_obj'")


async def _page(client, headers, name):
    did = (await client.post("/dashboards", headers=headers, json={"name": name})).json()["id"]
    pid = (await client.post(f"/dashboards/{did}/pages", headers=headers,
                             json={"name": "Стр"})).json()["id"]
    return did, pid


async def _cleanup(did):
    async with db.acquire() as conn:
        await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
        await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
        await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
        await conn.execute("delete from dashboards where id=$1::uuid", did)


async def _matrix(client, headers, pid, cfg):
    r = await client.post(f"/dashboard-pages/{pid}/widgets", headers=headers,
                          json={"name": "Матрица", "widget_type": "matrix", "config": cfg})
    assert r.status_code == 201, r.text
    return (await client.get(f"/widgets/{r.json()['id']}/data", headers=headers)).json()


def test_fold_is_chosen_by_the_meaning_of_the_indicator():
    """Правило свёртки одно на систему — им пользуются и матрица, и «Сравнение источников»."""
    assert fold_of("ИТОГО · Принято, ед.") == "sum"
    assert fold_of("Количество доставленных · Факт · нарастающим итогом**") == "last"
    assert fold_of("Доля доставленных, %") == "avg"
    # Явная единица количества отменяет догадку по словам (правка 04.09).
    assert fold_of("Компенсация 50% ОСАГО инвалидам · Принято, ед.") == "sum"


async def test_flow_is_summed_and_reports_per_month_are_named(client, admin_headers, mm_ds):
    """Поток складывается, а число отчётов в каждом месяце возвращается всегда.

    Месяцы неравны между собой (июль 3 отчёта, август 2), и без этой цифры
    сравнение месяцев вводит в заблуждение уверенным тоном.
    """
    did, pid = await _page(client, admin_headers, "zmm_flow")
    try:
        d = await _matrix(client, admin_headers, pid,
                          {"dataset_code": mm_ds, "value_field": "flow", "period_group": "month"})
        assert d["period_group"] == "month"
        assert d["periods"] == ["2026-07", "2026-08"]
        assert d["reports"] == [3, 2]
        assert d["total_reports"] == 5
        assert d["fold"] == "sum"
        by = {r["row"]: r for r in d["rows"]}
        # Горловка: июль (100+200+300)*0,6 = 360, август (400+500)*0,6 = 540.
        assert by["Горловка"]["values"] == [360.0, 540.0]
        assert by["Горловка"]["deltas"][1] == 180.0
        # Итог столбца — сумма по строкам: 600 и 900.
        assert d["col_totals"] == [600.0, 900.0]
        # Свежесть виджета — его последний ПОКАЗАННЫЙ столбец, а не дата выпуска.
        assert d["as_of"] == "2026-08"
    finally:
        await _cleanup(did)


async def test_cumulative_month_is_the_last_report_not_the_sum(client, admin_headers, mm_ds):
    """🔴 Накопительный итог месяца — последний отчёт. Сумма даёт несуществующее число."""
    did, pid = await _page(client, admin_headers, "zmm_cum")
    try:
        d = await _matrix(client, admin_headers, pid,
                          {"dataset_code": mm_ds, "value_field": "cum", "period_group": "month"})
        assert d["fold"] == "last"
        by = {r["row"]: r for r in d["rows"]}
        # Июль: последний отчёт 1500*0,6 = 900 (а НЕ 1000+1200+1500 = 3700*0,6).
        assert by["Горловка"]["values"] == [900.0, 1200.0]
        assert by["Донецк"]["values"] == [600.0, 800.0]
    finally:
        await _cleanup(did)


async def test_share_is_averaged_over_the_months_reports(client, admin_headers, mm_ds):
    """Доля усредняется: складывать проценты нельзя ни по строкам, ни по отчётам."""
    did, pid = await _page(client, admin_headers, "zmm_share")
    try:
        d = await _matrix(client, admin_headers, pid,
                          {"dataset_code": mm_ds, "by": "fields", "value_fields": ["share", "flow"],
                           "period_group": "month"})
        by = {r["field"]: r for r in d["rows"]}
        # Доля: строки усредняются внутри отчёта (30*0,6 и 30*0,4 → 15), затем
        # отчёты усредняются внутри месяца: (15+20+25)/3 = 20, (30+40)/2 = 35.
        assert by["share"]["values"] == [20.0, 35.0]
        assert by["share"]["aggregate"] == "avg"
        # Поток в той же матрице по-прежнему складывается.
        assert by["flow"]["values"] == [600.0, 900.0]
        # В разрезе по показателям общего способа свёртки нет: у каждой строки свой.
        assert d["fold"] is None
    finally:
        await _cleanup(did)


async def test_limit_applies_to_months_and_all_reports_are_read(client, admin_headers, mm_ds):
    """Предел считает МЕСЯЦЫ, а не отчёты.

    Если бы отчёты обрезались до группировки, «месяц» собрался бы из последних
    N выпусков — то есть из хвоста июля, а не из июля целиком.
    """
    did, pid = await _page(client, admin_headers, "zmm_limit")
    try:
        d = await _matrix(client, admin_headers, pid,
                          {"dataset_code": mm_ds, "value_field": "flow",
                           "period_group": "month", "max_periods": 2})
        assert d["periods"] == ["2026-07", "2026-08"]
        assert d["reports"] == [3, 2], "июль должен собраться из ВСЕХ своих отчётов"

        one = await _matrix(client, admin_headers, pid,
                            {"dataset_code": mm_ds, "value_field": "flow",
                             "period_group": "month", "max_periods": 2, "by": "rows"})
        assert one["total_reports"] == 5
    finally:
        await _cleanup(did)


async def test_by_reports_stays_the_old_way(client, admin_headers, mm_ds):
    """Без группировки поведение прежнее: столбец на каждый отчёт."""
    did, pid = await _page(client, admin_headers, "zmm_plain")
    try:
        d = await _matrix(client, admin_headers, pid,
                          {"dataset_code": mm_ds, "value_field": "flow"})
        assert d["period_group"] == "report"
        assert d["periods"] == list(RELEASES)
        assert d["reports"] is None and d["fold"] is None
    finally:
        await _cleanup(did)


def test_auto_build_picks_months_only_for_a_long_series():
    """Отчётов больше, чем матрица покажет, — берём месяцы; короткий ряд подробнее по отчётам."""
    from app.modules.dashboards._suggest import MATRIX_PERIODS, plan_auto_build

    def plan(periods: int):
        ds = [{
            "code": CODE, "name": "Форма", "periods": periods, "rows": 20,
            "period_dates": [f"2026-07-{d:02d}" for d in range(1, min(periods, 28) + 1)],
            "fields": [{"code": "flow", "name": "ИТОГО · Принято, ед."},
                       {"code": "f2", "name": "Заявок · Принято, ед."}],
            "sums": {}, "volumes": {"flow": 100.0, "f2": 50.0},
        }]
        out = plan_auto_build(ds, None)
        specs = out["widgets"] if isinstance(out, dict) else out
        return [w for w in specs if w["widget_type"] == "matrix"]

    long_series = plan(MATRIX_PERIODS + 1)
    assert long_series and long_series[0]["config"].get("period_group") == "month"
    assert "месяцам" in long_series[0]["name"]

    short_series = plan(4)
    assert short_series and "period_group" not in short_series[0]["config"]
    assert "датам" in short_series[0]["name"]


# ── Водопад: из чего сложился итог ─────────────────────────────────────────

async def test_waterfall_by_periods_on_a_cumulative_field(client, admin_headers, mm_ds):
    """🔴 Накопительный итог: вклад периода — ПРИРОСТ, а не само значение.

    Найдено осмотром дашборда заказчика: авто-сборка берёт накопительную графу и
    называет виджет «вклад периодов», а данные приходили ПО СТРОКАМ — у формы
    МАХ водопад из одного столбика объяснял 2 537 581 самим собой.

    Первый столбик — уровень на начало отрезка: начни водопад с нуля, он
    приписал бы первому периоду всё накопленное до него.
    """
    did, pid = await _page(client, admin_headers, "zmm_wf_cum")
    try:
        r = await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                              json={"name": "Водопад", "widget_type": "waterfall",
                                    "config": {"dataset_code": mm_ds, "value_field": "cum",
                                               "by": "periods"}})
        d = (await client.get(f"/widgets/{r.json()['id']}/data", headers=admin_headers)).json()
        assert d["by"] == "periods" and d["fold"] == "last"
        # Строки свёрнуты суммой внутри отчёта: 1000 → 1200 → 1500 → 1800 → 2000.
        assert d["categories"][0] == "2026-07-05"
        assert d["values"] == [1000.0, 200.0, 300.0, 300.0, 200.0]
        # Сумма столбиков = последнее значение: на этом водопад и держится.
        assert sum(d["values"]) == 2000.0
        assert "уровень на начало" in (d["note"] or "")
    finally:
        await _cleanup(did)


async def test_waterfall_by_periods_on_a_flow_field(client, admin_headers, mm_ds):
    """Поток: вклад периода — само значение, итог — сумма."""
    did, pid = await _page(client, admin_headers, "zmm_wf_flow")
    try:
        r = await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                              json={"name": "Водопад", "widget_type": "waterfall",
                                    "config": {"dataset_code": mm_ds, "value_field": "flow",
                                               "by": "periods"}})
        d = (await client.get(f"/widgets/{r.json()['id']}/data", headers=admin_headers)).json()
        assert d["fold"] == "sum" and d["note"] is None
        assert d["values"] == [100.0, 200.0, 300.0, 400.0, 500.0]
        assert sum(d["values"]) == 1500.0
    finally:
        await _cleanup(did)


async def test_waterfall_refuses_a_share_and_says_why(client, admin_headers, mm_ds):
    """Доля: вид не строится вовсе. Правдоподобная с виду картинка хуже её отсутствия."""
    did, pid = await _page(client, admin_headers, "zmm_wf_share")
    try:
        r = await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                              json={"name": "Водопад", "widget_type": "waterfall",
                                    "config": {"dataset_code": mm_ds, "value_field": "share",
                                               "by": "periods"}})
        resp = await client.get(f"/widgets/{r.json()['id']}/data", headers=admin_headers)
        assert resp.status_code >= 400
        assert "не складываются" in resp.text
    finally:
        await _cleanup(did)


def test_waterfall_by_rows_keeps_the_sum_equal_to_the_total():
    """🔴 Хвост складывается в «Прочие», а не отбрасывается.

    У столбчатого графика лишние строки можно просто не показать: каждый столбик
    сам по себе. Водопад держится на равенстве «сумма вкладов = итог», и
    отбрасывание сломало бы саму арифметику, а не только полноту.
    """
    from app.modules.dashboards._widgetcalc import MAX_WF_BARS, _trim_waterfall

    cats = [f"Отделение {i}" for i in range(30)]
    vals = [float(i) for i in range(30)]
    res = {"categories": list(cats), "values": list(vals)}
    _trim_waterfall(res)

    assert len(res["categories"]) == MAX_WF_BARS
    assert "Прочие" in res["categories"][-1]
    assert res["hidden_rows"] == 30 - (MAX_WF_BARS - 1)
    # Главное: сумма не изменилась.
    assert sum(res["values"]) == sum(vals)


def test_auto_build_asks_the_waterfall_for_periods():
    """Разрез задаётся ЯВНО: иначе виджет снова показывал бы строки под именем «вклад периодов»."""
    from app.modules.dashboards._suggest import by_meaning_specs

    fields = [{"code": "cum", "name": "Количество доставленных · Факт · нарастающим итогом"}]
    specs = by_meaning_specs(fields, rows=3, periods=6, values={"cum": 100.0},
                             volumes={"cum": 100.0})
    wf = [s for s in specs if s["kind"] == "waterfall"]
    assert wf, "на накопительной графе с историей водопад должен предлагаться"
    assert wf[0]["config"]["by"] == "periods"
