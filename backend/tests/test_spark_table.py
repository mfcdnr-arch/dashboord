"""Строки с мини-графиками: как двигалась каждая строка формы.

Матрица «строка × дата» отвечает тем же разрезом, но ЧИСЛАМИ: на двенадцати
столбцах она перестаёт помещаться, а у заказчика строк шестьдесят две. Здесь у
каждой строки одна линия — видно форму движения (растёт, просела, скачет), и
таких строк помещается сколько угодно.

Проверяется главным образом то, на чём такой виджет легко начинает врать:
прирост через пропуск в ряду, процент от нуля и порядок строк.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from app.modules.dashboards import _suggest

CODE = "zspark_ds"
FIELD = "spark_val"
# Четыре отчёта. У «Донецка» ровный рост, у «Макеевки» ПРОПУСК в середине
# (отчёта за неделю не было — это не ноль), у «Горловки» падение, у «Тореза»
# старт с нуля: процент прироста от нуля не считается вовсе.
PERIODS = ["2026-07-01", "2026-07-08", "2026-07-15", "2026-07-22"]
DATA = {
    "Донецк":   [100.0, 120.0, 140.0, 160.0],
    "Макеевка": [80.0, None, None, 95.0],
    "Горловка": [200.0, 180.0, 170.0, 150.0],
    "Торез":    [0.0, 0.0, 0.0, 5.0],
}


@pytest.fixture
async def spark_ds(ids):
    """Свой датасет на четыре выпуска: `seed_dataset` даёт только два."""
    async with db.acquire() as conn:
        await conn.execute("delete from dataset_values where dataset_release_id in "
                           "(select id from dataset_releases where code=$1)", CODE)
        await conn.execute("delete from dataset_releases where code=$1", CODE)
        for pi, period in enumerate(PERIODS):
            rel = await conn.fetchval(
                "insert into dataset_releases(organization_id,code,name,status,"
                "reporting_period_start,created_by) values($1,$2,'Спарк',$3,$4::text::date,$5) "
                "returning id", ids["org"], CODE, "released", period, ids["admin"])
            for ri, (label, series) in enumerate(DATA.items()):
                if series[pi] is None:
                    continue          # отчёта по этой строке не было — не ноль
                await conn.execute(
                    "insert into dataset_values(dataset_release_id,row_index,row_label,"
                    "canonical_field_code,value_number) values($1,$2,$3,$4,$5)",
                    rel, ri, label, FIELD, series[pi])
    yield CODE
    async with db.acquire() as conn:
        await conn.execute("delete from dataset_values where dataset_release_id in "
                           "(select id from dataset_releases where code=$1)", CODE)
        await conn.execute("delete from dataset_releases where code=$1", CODE)


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


async def _data(client, headers, pid, cfg, name="Мини-графики"):
    r = await client.post(f"/dashboard-pages/{pid}/widgets", headers=headers,
                          json={"name": name, "widget_type": "spark_table", "config": cfg})
    assert r.status_code == 201, r.text
    return (await client.get(f"/widgets/{r.json()['id']}/data", headers=headers)).json()


def _by_label(d):
    return {r["label"]: r for r in d["rows"]}


async def test_each_row_gets_its_own_trajectory(client, admin_headers, spark_ds):
    """Строка формы, её ряд за отчёты и текущее значение."""
    did, pid = await _page(client, admin_headers, "zspark_basic")
    try:
        d = await _data(client, admin_headers, pid,
                        {"dataset_code": spark_ds, "value_field": FIELD, "periods": 4})
        assert d["type"] == "spark_table"
        assert d["periods"] == PERIODS and d["shown_periods"] == 4
        rows = _by_label(d)
        assert rows["Донецк"]["values"] == DATA["Донецк"]
        assert rows["Донецк"]["last"] == 160.0
        assert rows["Донецк"]["delta"] == 20.0
        assert round(rows["Донецк"]["delta_pct"], 2) == 14.29
    finally:
        await _cleanup(did)


async def test_gap_in_the_series_is_not_a_zero(client, admin_headers, spark_ds):
    """🔴 Пропущенный отчёт — не ноль, и прирост считается к предыдущему НЕПУСТОМУ.

    Считай мы прирост к соседней клетке, у «Макеевки» вышло бы «+95 из нуля»,
    то есть выдуманный скачок там, где отчёта просто не было.
    """
    did, pid = await _page(client, admin_headers, "zspark_gap")
    try:
        d = await _data(client, admin_headers, pid,
                        {"dataset_code": spark_ds, "value_field": FIELD, "periods": 4})
        mk = _by_label(d)["Макеевка"]
        assert mk["values"] == [80.0, None, None, 95.0], "пропуск остаётся пропуском"
        assert mk["last"] == 95.0 and mk["prev"] == 80.0
        assert mk["delta"] == 15.0, "сравниваем с последним отчётом, где данные были"
    finally:
        await _cleanup(did)


async def test_growth_from_zero_has_no_percent(client, admin_headers, spark_ds):
    """Процент от нуля не считаем: «рост на бесконечность» ничего не сообщает."""
    did, pid = await _page(client, admin_headers, "zspark_zero")
    try:
        d = await _data(client, admin_headers, pid,
                        {"dataset_code": spark_ds, "value_field": FIELD, "periods": 4})
        torez = _by_label(d)["Торез"]
        assert torez["delta"] == 5.0, "прирост в единицах показателя есть"
        assert torez["delta_pct"] is None, "а процента от нуля не существует"
    finally:
        await _cleanup(did)


async def test_sort_answers_different_questions(client, admin_headers, spark_ds):
    """Порядок задаёт человек: «кто крупный» против «кто просел»."""
    did, pid = await _page(client, admin_headers, "zspark_sort")
    try:
        by_value = await _data(client, admin_headers, pid,
                               {"dataset_code": spark_ds, "value_field": FIELD, "sort": "value"})
        assert [r["label"] for r in by_value["rows"]][0] == "Донецк", "крупнейший сверху"

        by_change = await _data(client, admin_headers, pid,
                                {"dataset_code": spark_ds, "value_field": FIELD, "sort": "change"},
                                name="По изменению")
        # Горловка потеряла 20 — она и должна оказаться первой.
        assert by_change["rows"][0]["label"] == "Горловка"
        assert by_change["rows"][0]["delta"] == -20.0
        as_form = await _data(client, admin_headers, pid,
                              {"dataset_code": spark_ds, "value_field": FIELD, "sort": "form"},
                              name="Как в форме")
        assert [r["label"] for r in as_form["rows"]] == list(DATA), "порядок формы сохранён"

        # 🔴 Не сдвинувшиеся строки уходят в КОНЕЦ. Найдено на живых данных: у
        # формы МВД почти все отделения стоят на нуле, и они занимали весь
        # первый экран, вытесняя вниз единственное реально выросшее.
        # Строку добавляем ПОСЛЕ проверки порядка формы — иначе она сама же в
        # эту проверку и попадёт.
        async with db.acquire() as conn:
            for offset in (0, 1):
                rel = await conn.fetchval(
                    "select id from dataset_releases where code=$1 "
                    "order by reporting_period_start desc offset $2 limit 1", spark_ds, offset)
                await conn.execute(
                    "insert into dataset_values(dataset_release_id,row_index,row_label,"
                    "canonical_field_code,value_number) values($1,9,'Стоячее',$2,7)", rel, FIELD)
        moved = await _data(client, admin_headers, pid,
                            {"dataset_code": spark_ds, "value_field": FIELD, "sort": "change"},
                            name="По изменению 2")
        assert moved["rows"][-1]["label"] == "Стоячее", "не сдвинувшаяся строка — в конце"
        assert moved["rows"][0]["label"] == "Горловка", "просевшая по-прежнему первая"
    finally:
        await _cleanup(did)


async def test_line_length_is_limited_and_the_truth_is_told(client, admin_headers, spark_ds):
    """Линия короче ряда — и сколько отчётов есть НА САМОМ ДЕЛЕ, сказано.

    Умолчать об этом значило бы выдать три последних отчёта за всю историю.
    """
    did, pid = await _page(client, admin_headers, "zspark_limit")
    try:
        d = await _data(client, admin_headers, pid,
                        {"dataset_code": spark_ds, "value_field": FIELD, "periods": 2})
        assert d["shown_periods"] == 2 and d["total_periods"] == 4
        assert d["periods"] == PERIODS[-2:], "берутся ПОСЛЕДНИЕ отчёты, а не первые"
    finally:
        await _cleanup(did)


def test_auto_build_needs_both_rows_and_history():
    """Вид ставится, только когда есть и строки, и чем их двигать.

    На одной строке подробнее отвечает «Динамика», на двух отчётах линия
    вырождается в отрезок и формы движения не показывает вовсе.
    """
    fields = [{"code": "fact", "name": "Заявлений принято · Факт · нарастающим итогом"}]

    def kinds(rows, periods):
        ds = [{"code": "t", "name": "Форма", "periods": periods, "releases": periods,
               "fields": fields, "rows": rows,
               "period_dates": ["2026-07-%02d" % (1 + 7 * i) for i in range(periods)]}]
        return [s["widget_type"] for s in _suggest.plan_auto_build(ds, None)]

    assert "spark_table" not in kinds(rows=1, periods=4), "одной строке нужна «Динамика»"
    assert "spark_table" not in kinds(rows=8, periods=2), "на двух точках линии нет"
    assert "spark_table" in kinds(rows=8, periods=4)
