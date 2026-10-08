"""Подсчёт строк формы (_tally, 08.10.2026): «сколько вопросов в работе».

До этой правки все виды работали с числовыми графами, и формы-реестры
(проблемные вопросы, итоги и планы недели отчёта для Минэкономразвития)
получали на дашборде одни таблицы. Проверяем режим `count` у карточки,
столбиков, круговой и тепловой карты и отбор строк таблицы — через тот же
предпросмотр, что у конструктора, и прямые вызовы там, где нужны права на строки.
"""
from datetime import date

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db  # noqa: E402
from app.modules.dashboards import _coverage, _explain, _levels, _tally  # noqa: E402
from app.modules.dashboards._base import DashboardError  # noqa: E402

CODE = "ztest_tally_ds"
D1, D2 = date(2026, 9, 29), date(2026, 10, 6)
# Реестр проблемных вопросов: статус, уровень, оценка, вероятность, влияние, срок.
ROWS_W1 = [
    ("Вопрос А", "В работе", "Высокий", 16, 4, 4, "До 01.10.2026"),
    ("Вопрос Б", "в работе", "Средний", 9, 3, 3, "2026-10-20 00:00:00"),
]
ROWS_W2 = ROWS_W1 + [
    ("Вопрос В", "Вопрос решен", "Снят", 2, 1, 2, "на постоянной основе"),
    ("Вопрос Г", "В работе", "Высокий", 20, 5, 4, "05.10.2026"),
    ("Вопрос Д", "Не актуально", None, 6, 2, 3, None),
]
FIELDS = [("status", "Статус", "text"), ("uroven", "Уровень риска", "text"),
          ("ocenka", "Оценка риска", "number"), ("ver", "Вероятность", "number"),
          ("vliyanie", "Влияние", "number"), ("srok", "Срок решения", "text")]


async def _release(conn, f, period, rows):
    rid = await conn.fetchval(
        "insert into dataset_releases(organization_id,code,name,status,reporting_period_start,created_by,"
        "object_id) values($1,$2,'Реестр',$3,$4,$5,$6) returning id",
        f["org"], CODE, "validated", period, f["admin"], f["oid"])
    for i, (label, *vals) in enumerate(rows):
        for (code, _name, dt), v in zip(FIELDS, vals, strict=True):
            if v is None:
                continue
            col = "value_number" if dt == "number" else "value_text"
            await conn.execute(
                f"insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,{col}) "
                "values($1,$2,$3,$4,$5)", rid, i, label, code, v)
    for code, _name, _dt in FIELDS:
        await conn.execute(
            "insert into dataset_release_fields(dataset_release_id,canonical_field_code) values($1,$2)", rid, code)
    return rid


@pytest_asyncio.fixture
async def form(ids):
    async with db.acquire() as conn:
        await conn.execute("delete from dataset_values where dataset_release_id in "
                           "(select id from dataset_releases where code=$1)", CODE)
        await conn.execute("delete from dataset_release_fields where dataset_release_id in "
                           "(select id from dataset_releases where code=$1)", CODE)
        await conn.execute("delete from dataset_releases where code=$1", CODE)
        await conn.execute("delete from objects where name='ztest_tally_obj'")
        oid = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,'ztest_tally_obj') returning id", ids["org"])
        for code, name, dt in FIELDS:
            await conn.execute(
                "insert into canonical_fields(object_id,code,name,data_type,created_by) values($1,$2,$3,$4,$5)",
                oid, code, name, dt, ids["admin"])
        f = {"oid": oid, "org": ids["org"], "admin": ids["admin"]}
        await _release(conn, f, D1, ROWS_W1)
        await _release(conn, f, D2, ROWS_W2)
    yield f
    async with db.acquire() as conn:
        await conn.execute("delete from dataset_values where dataset_release_id in "
                           "(select id from dataset_releases where code=$1)", CODE)
        await conn.execute("delete from dataset_release_fields where dataset_release_id in "
                           "(select id from dataset_releases where code=$1)", CODE)
        await conn.execute("delete from dataset_releases where code=$1", CODE)
        await conn.execute("delete from canonical_fields where object_id=$1", oid)
        await conn.execute("delete from objects where id=$1", oid)


async def _pv(client, headers, wt, cfg):
    r = await client.post("/widgets/preview", headers=headers,
                          json={"widget_type": wt, "name": "T", "config": {"dataset_code": CODE, **cfg}})
    assert r.status_code == 200, r.text
    return r.json()


def test_values_compare_as_people_read_them():
    """Регистр, «ё», пробелы и «5.0» против «5» сравнение не различает."""
    assert _tally._norm("  В  работе ") == _tally._norm("в работе")
    assert _tally._norm("Решён") == _tally._norm("решен")
    assert _tally._norm(5.0) == _tally._norm("5") == _tally._norm("5,0")
    assert _tally._label(4.0) == "4" and _tally._label(None) == _tally.EMPTY_LABEL
    assert _tally.parse_date("До 13.10.2026") == date(2026, 10, 13)
    assert _tally.parse_date("2026-10-06 00:00:00") == date(2026, 10, 6)
    assert _tally.parse_date("на постоянной основе") is None


def test_bad_condition_is_named_not_ignored():
    """Молча пропущенное условие дало бы правдоподобное, но неверное число."""
    for where, msg in ([{"op": "eq"}], "не указана графа"), ([{"field": "x", "op": "bad"}], "неизвестное"), \
            ([{"field": "x", "op": "gte", "value": "много"}], "нужно число"), \
            ([{"field": "x", "op": "in", "value": "a"}], "нужен список"):
        with pytest.raises(DashboardError, match=msg):
            _tally.check_where(where)


async def test_card_counts_rows_by_conditions(client, admin_headers, form):
    """Карточка: число строк последнего отчёта под условиями, без учёта регистра."""
    d = await _pv(client, admin_headers, "kpi", {"count": True})
    assert d["value"] == 5 and d["rows_total"] == 5 and d["count"] is True
    d = await _pv(client, admin_headers, "kpi", {"count": True,
                                                 "where": [{"field": "status", "op": "eq", "value": "в работе"}]})
    assert d["value"] == 3, "«В работе» и «в работе» — один статус"
    d = await _pv(client, admin_headers, "kpi", {"count": True, "where": [
        {"field": "ocenka", "op": "gte", "value": 15}, {"field": "status", "op": "ne", "value": "Вопрос решен"}]})
    assert d["value"] == 2, "условия складываются через «И»"
    d = await _pv(client, admin_headers, "kpi", {"count": True, "where": [
        {"field": "uroven", "op": "in", "value": ["Высокий", "Средний"]}]})
    assert d["value"] == 3
    d = await _pv(client, admin_headers, "kpi", {"count": True, "where": [{"field": "uroven", "op": "empty"}]})
    assert d["value"] == 1, "пустая графа — отдельное условие, а не «не равно»"


async def test_overdue_counts_against_the_report_date_and_names_unparsed(client, admin_headers, form):
    """Срок сравнивается с датой ОТЧЁТА (06.10), а строки без распознанной даты
    названы числом — иначе «просрочено 2» читалось бы как «у остальных порядок»."""
    d = await _pv(client, admin_headers, "kpi", {"count": True, "where": [
        {"field": "srok", "op": "date_before_report"}]})
    assert d["value"] == 2, d  # 01.10 и 05.10 раньше 06.10; 20.10 — нет
    assert "У 1 строки дата не распознана" in d["note"] and "она не вошла" in d["note"], d
    # Старый отчёт (29.09) судит по своей дате: 01.10 тогда ещё не истёк.
    d = await _pv(client, admin_headers, "kpi", {"count": True, "period": "2026-09-29",
                                                 "where": [{"field": "srok", "op": "date_before_report"}]})
    assert d["value"] == 0, d


async def test_split_by_values_orders_numbers_and_puts_empty_last(client, admin_headers, form):
    """Столбики: число строк по значениям. Числа — по возрастанию, текст — по
    частоте, «не заполнено» — последним и названо, а не потеряно."""
    d = await _pv(client, admin_headers, "bar", {"count": True, "group_by": "uroven"})
    assert d["categories"] == ["Высокий", "Снят", "Средний", _tally.EMPTY_LABEL]
    assert d["values"] == [2, 1, 1, 1] and sum(d["values"]) == 5
    d = await _pv(client, admin_headers, "pie", {"count": True, "group_by": "ver"})
    assert d["categories"] == ["1", "2", "3", "4", "5"] and sum(d["values"]) == 5
    # Разбивка сравнивает значения ТАК ЖЕ, как условие отбора: «В работе» и
    # «в работе» — один статус, подписанный записью, что встречается чаще.
    # До правки это были два сектора при одном числе у фильтра «в работе».
    d = await _pv(client, admin_headers, "pie", {"count": True, "group_by": "status"})
    assert d["categories"][0] == "В работе" and d["values"][0] == 3, d
    assert "в работе" not in d["categories"]
    # Заданный порядок тоже не зависит от регистра: уровень из классификатора,
    # вписанный строчными, находит свои строки, а не уходит «вне шкалы».
    d = await _pv(client, admin_headers, "bar", {"count": True, "group_by": "uroven",
                                                 "group_values": ["высокий", "Средний", "Низкий"]})
    assert d["categories"] == ["высокий", "Средний", "Низкий"] and d["values"] == [2, 1, 0], d
    assert "2 строки со значением вне заданной шкалы не показаны" in (d.get("note") or ""), d


async def test_risk_matrix_keeps_the_whole_scale_and_names_what_falls_outside(client, admin_headers, form):
    """Матрица: заданная шкала видна целиком (пустая клетка — тоже ответ), а
    значение вне шкалы не пропадает молча."""
    d = await _pv(client, admin_headers, "heatmap", {
        "count": True, "group_by": "ver", "group_by2": "vliyanie",
        "group_values": [5, 4, 3, 2, 1], "group_values2": [1, 2, 3, 4, 5]})
    assert d["rows"] == ["5", "4", "3", "2", "1"] and d["columns"] == ["1", "2", "3", "4", "5"]
    assert len(d["cells"]) == 25 and sum(c[2] for c in d["cells"]) == 5
    cell = {(d["rows"][c[1]], d["columns"][c[0]]): c[2] for c in d["cells"]}
    assert cell[("4", "4")] == 1 and cell[("5", "4")] == 1 and cell[("5", "5")] == 0
    d = await _pv(client, admin_headers, "heatmap", {
        "count": True, "group_by": "ver", "group_by2": "vliyanie",
        "group_values": [1, 2, 3], "group_values2": [1, 2, 3, 4, 5]})
    assert sum(c[2] for c in d["cells"]) == 3 and "2 строки со значением вне заданной шкалы не показаны" in d["note"]


async def test_table_shows_only_matching_rows(client, admin_headers, form):
    """«Лента» — таблица из строк, подходящих под условие."""
    d = await _pv(client, admin_headers, "table", {"where": [{"field": "uroven", "op": "eq", "value": "высокий"}]})
    assert [r["row"] for r in d["rows"]] == ["Вопрос А", "Вопрос Г"]


async def test_card_trend_counts_each_report(client, admin_headers, form):
    """Прирост и мини-график карточки — по числу строк в каждом отчёте."""
    d = await _pv(client, admin_headers, "kpi", {"count": True, "compare_prev": True, "spark": True,
                                                 "where": [{"field": "status", "op": "eq", "value": "В работе"}]})
    assert d["spark"] == [2, 3] and d["prev_value"] == 2 and d["delta"] == 1


async def test_row_rights_apply_to_counts(form):
    """Подсчёт не вправе стать обходным путём к строкам, которых человеку не видно."""
    async with db.acquire() as conn:
        res = await _tally.count_value(conn, form["org"], {"dataset_code": CODE, "count": True},
                                       allowed={"Вопрос А", "Вопрос Г"})
        assert res["value"] == 2
        res = await _tally.count_by(conn, form["org"], {"dataset_code": CODE, "group_by": "uroven"},
                                    allowed={"Вопрос А"})
        assert res["categories"] == ["Высокий"] and res["values"] == [1]


def test_count_widget_is_silent_inside_a_ladder_branch_and_names_its_axes():
    """Строк формы столько же в любой ветке — число «внутри Росреестра» было бы
    числом по всей форме под чужим именем. Ось подсчёта — показанная графа."""
    assert _levels.narrow_cfg({"dataset_code": CODE, "count": True}, {}, " · ", ["Росреестр"]) is None
    assert ("f", "uroven") in _coverage.named_fields({"dataset_code": "f", "count": True, "group_by": "uroven"})


def test_explanation_says_rows_are_counted():
    ctx = {"fields": {(CODE, "status"): {"name": "Статус"}, (CODE, "srok"): {"name": "Срок решения"}},
           "forms": {CODE: "Реестр"}}
    s = _explain.widget_sections({"widget_type": "kpi", "config": {
        "dataset_code": CODE, "count": True, "where": [
            {"field": "status", "op": "eq", "value": "В работе"}, {"field": "srok", "op": "date_before_report"}]}},
        ctx)
    assert s["what"].startswith("Число строк формы «Реестр» где «Статус» равно «В работе»"), s
    assert "срок истёк" in s["what"] and "ОТЧЁТНОЙ датой" in s["caveats"]
