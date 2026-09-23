"""Итоговые строки, попавшие в данные, находятся до выпуска.

Такая строка складывается с остальными, и суммы на карточках удваиваются.
Правило проверено на настоящем листе РЦО за 15.09.2026: блок «ИТОГО»
(«Принято/Выдано/Отказ») подписан не словом «итого», а мерой, — ловится по
сумме; «На вчера» и «Накопительный» лежат ниже итога.
"""
from app.modules.ingestion import mapping


def _rco_like():
    rows = [
        ["1", "Отделение № 1", "10", "4"],
        ["2", "Отделение № 2", "20", "6"],
        ["3", "Отделение № 3", "5", "0"],
        ["4", "Отделение № 4", "7", "3"],
        ["ИТОГО", "Принято", "42", "13"],        # суммы строк над ней
        ["", "", "", ""],
        ["", "На вчера", "", ""],
        ["", "Принято", "7300", "2100"],        # нарастающий итог: с отделениями не сходится
    ]
    return list(enumerate(rows))


def test_total_block_is_found_by_sum_and_everything_below_it():
    found = mapping.total_like_rows(_rco_like(), numeric_cols=[2, 3], text_cols=[1])
    assert [(x["index"], x["reason"]) for x in found] == [(4, "sum"), (7, "below_total")]


def test_word_total_in_any_text_column_counts():
    rows = [["1", "А", "1"], ["2", "Б", "2"], ["Всего", "", "3"]]
    found = mapping.total_like_rows(list(enumerate(rows)), numeric_cols=[2], text_cols=[0, 1])
    assert [(x["index"], x["reason"]) for x in found] == [(2, "label")]


def test_ordinary_rows_are_not_mistaken_for_totals():
    """Строка, совпавшая с нарастающей суммой по ОДНОЙ графе, — не итог."""
    rows = [
        ["А", "1", "5"], ["Б", "1", "7"], ["В", "2", "9"],
        ["Г", "4", "30"],   # 4 = 1+1+2 по первой графе — случайность, по второй нет
        ["Д", "3", "8"],
    ]
    assert mapping.total_like_rows(list(enumerate(rows)), numeric_cols=[1, 2], text_cols=[0]) == []


def test_footnote_without_numbers_is_left_to_the_other_hint():
    rows = [["А", "1"], ["Б", "2"], ["В", "3"], ["Данные нарастающим итогом с 1 января", ""]]
    assert mapping.total_like_rows(list(enumerate(rows)), numeric_cols=[1], text_cols=[0]) == []


def test_release_warning_names_the_rows():
    fields = [
        {"column_index": 1, "field_code": "name", "field_name": "Отделение", "data_type": "text",
         "is_row_label": True},
        {"column_index": 2, "field_code": "p", "field_name": "Принято", "data_type": "number"},
        {"column_index": 3, "field_code": "v", "field_name": "Выдано", "data_type": "number"},
    ]
    w = mapping._total_row_warning([r for _i, r in _rco_like()], fields)
    assert w["code"] == "total_row_in_data" and w["count"] == 2
    assert "удвоятся" in w["message"] and "«Принято»" in w["message"]
    assert mapping._total_row_warning([r for _i, r in _rco_like()[:4]], fields) is None


def test_file_total_check_catches_a_row_dropped_by_mistake():
    from app.modules.ingestion import analyze
    area = [["№", "Отделение", "Принято", "Выдано"]] + [r for _i, r in _rco_like()]
    hdr = 1
    cols = analyze.analyze_columns(area, hdr)
    names = [c.source_header for c in cols]
    all_items = mapping.data_row_items(area, hdr, ())
    totals = mapping.total_like_rows(all_items, [2, 3], [1])

    ok = mapping._file_total_check(area, all_items, totals, cols, names)
    assert (ok["checked"], ok["matched"]) == (2, 2)

    dropped = mapping.data_row_items(area, hdr, [2])  # сняли «Отделение № 2»
    bad = mapping._file_total_check(area, dropped, totals, cols, names)
    assert bad["matched"] == 0 and bad["examples"][0]["file"] == 42 and bad["examples"][0]["ours"] == 22
