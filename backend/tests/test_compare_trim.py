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
"""
from app.modules.dashboards._widgetcalc import (
    MAX_COMPARE_BARS,
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
