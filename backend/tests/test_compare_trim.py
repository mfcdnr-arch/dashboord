"""Виджет «Сравнение показателей» на широкой форме.

🔴 Найдено снимком заказчика 04.09.2026. У ежедневного отчёта РЦО 62 отделения
и 24 выбранных показателя — виджет строил 24 серии × 62 категории, то есть
**1 488 столбиков**: ось рисовала 62 повёрнутые подписи, легенда разбивалась на
17 страниц, а сами столбики становились волосяными линиями.

Ограничение по ПРОИЗВЕДЕНИЮ, а не по каждому измерению отдельно, — и это
главное решение. Ограничь мы число показателей, порог неминуемо оказался бы
меньше 13, и порезанной оказалась бы форма МАХ: одна строка, 13 показателей,
13 столбиков — ровно тот случай, ради которого вид и заводился и который
ломать нельзя. Тест держит обе стороны.

Дополнено 11.09.2026 по замечанию заказчика («столбики волосяные, опустить
предел для двух серий»): у ЧИСЛА КАТЕГОРИЙ свой предел, отдельный от
произведения. Место на оси под категорию — это ширина графика, делённая на их
число, и от количества показателей она не зависит вовсе: при двух мерах
произведение разрешало 40 отделений, то есть по 14px на категорию.
"""
from app.modules.dashboards._widgetcalc import (
    MAX_COMPARE_BARS,
    MAX_COMPARE_CATS,
    MIN_COMPARE_ROWS,
    _trim_compare,
)


def _res(rows: int, fields: int) -> dict:
    """Прямоугольник rows × fields с убывающим объёмом: первая строка крупнее."""
    cats = [f"Отделение {i}" for i in range(rows)]
    series = [{"name": f"Показатель {f}", "data": [float((rows - i) * (fields - f)) for i in range(rows)]}
              for f in range(fields)]
    return {"categories": cats, "series": series}


def test_max_form_is_untouched():
    """Форма МАХ: одна строка, 13 показателей — виджет работает правильно."""
    res = _res(1, 13)
    before = ([*res["categories"]], [s["name"] for s in res["series"]])
    _trim_compare(res, {})
    assert (res["categories"], [s["name"] for s in res["series"]]) == before
    # Ни слова про обрезку: её не было.
    assert "hidden_rows" not in res and "hidden_series" not in res


def test_wide_form_is_trimmed_to_a_readable_number_of_bars():
    """РЦО: 62 × 24 = 1 488 столбиков сокращаются до читаемого числа."""
    res = _res(62, 24)
    _trim_compare(res, {})
    bars = len(res["categories"]) * len(res["series"])
    assert bars <= MAX_COMPARE_BARS
    assert len(res["categories"]) >= MIN_COMPARE_ROWS


def test_trimming_is_never_silent():
    """Сколько убрано и из скольких — сказано числами, а не «часть данных»."""
    res = _res(62, 24)
    _trim_compare(res, {})
    assert res["total_rows"] == 62 and res["total_series"] == 24
    assert res["hidden_rows"] == 62 - len(res["categories"])
    assert res["hidden_series"] == 24 - len(res["series"])
    assert res["hidden_rows"] > 0


def test_rows_are_cut_before_indicators():
    """Сокращаем сперва строки: вопрос вида — про показатели, строки лишь разрез.

    К тому же взрывается обычно именно число строк: их шестьдесят, а
    показателей десяток.
    """
    res = _res(62, 8)
    _trim_compare(res, {})
    # Восьми показателей хватает, чтобы уложиться в порог одними строками.
    assert len(res["series"]) == 8
    assert len(res["categories"]) < 62


def test_the_biggest_are_kept_and_file_order_is_preserved():
    """Оставляем самые крупные, но показываем в порядке формы.

    Порядок граф в файле о важности не говорит ничего — поэтому ОТБИРАЕМ по
    объёму. Но перетасовка при каждом открытии мешала бы сверять виджет с
    файлом, поэтому ПОКАЗЫВАЕМ в исходном порядке.
    """
    res = _res(62, 24)
    kept = list(res["categories"])
    _trim_compare(res, {})
    # Самая крупная строка (нулевая) на месте, самая мелкая (последняя) — нет.
    assert kept[0] in res["categories"]
    assert kept[-1] not in res["categories"]
    # Порядок не перетасован: он подмножество исходного в том же порядке.
    idx = [kept.index(c) for c in res["categories"]]
    assert idx == sorted(idx)


def test_empty_result_does_not_crash():
    """Пустой набор — не ошибка: датасет может не иметь данных за период."""
    res = {"categories": [], "series": []}
    _trim_compare(res, {})
    assert res == {"categories": [], "series": []}


def test_none_values_do_not_break_volume():
    """Пропуск в форме — не ноль и не повод упасть при подсчёте объёма."""
    res = _res(62, 24)
    res["series"][0]["data"][0] = None
    res["series"][3]["data"] = [None] * 62
    _trim_compare(res, {})
    assert len(res["categories"]) * len(res["series"]) <= MAX_COMPARE_BARS


def test_two_indicators_do_not_earn_forty_rows():
    """«Окна и часы»: 62 отделения × 2 меры.

    Порог по произведению разрешал здесь 40 строк (40 × 2 = 80), и на карточке
    в половину ряда на категорию оставалось 14px: столбики волосяные, а часть
    повёрнутых подписей ECharts прятал как налезающие — то есть столбик
    оставался вообще без имени.
    """
    res = _res(62, 2)
    _trim_compare(res, {})
    # Показатели не режем: их и так два, резать нечего.
    assert len(res["series"]) == 2
    assert len(res["categories"]) == MAX_COMPARE_CATS
    assert res["hidden_rows"] == 62 - MAX_COMPARE_CATS
    assert res["hidden_series"] == 0
    assert res["total_rows"] == 62


def test_category_cap_applies_even_when_the_product_fits():
    """20 строк × 2 меры — это 40 столбиков, и порог по произведению молчит.

    Но подписей на оси всё равно 20, и предел по категориям обязан сработать
    раньше: иначе читаемость оси зависела бы от числа показателей, которое к
    ширине места на оси отношения не имеет.
    """
    res = _res(20, 2)
    _trim_compare(res, {})
    assert len(res["categories"]) == MAX_COMPARE_CATS
    assert res["hidden_rows"] == 20 - MAX_COMPARE_CATS


def test_wide_form_with_many_indicators_is_not_cut_further():
    """Предел по категориям не должен ужимать случай, где режет произведение.

    У РЦО 62 × 24: произведение оставляет 6 строк и 13 показателей — это уже
    меньше предела по категориям, и второе правило здесь молчит.
    """
    res = _res(62, 24)
    _trim_compare(res, {})
    assert len(res["categories"]) == MIN_COMPARE_ROWS
    assert len(res["series"]) > MIN_COMPARE_ROWS
