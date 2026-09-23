"""Отчётная дата выпуска сверяется с именем файла и листа.

Ошибка в дате тихая: выпуск ложится в ряд не той неделей, а на графике это
выглядит обычной точкой.
"""
from datetime import date

from app.modules.ingestion import mapping

TODAY = date(2026, 9, 23)


def _codes(ws):
    return [w["code"] for w in ws]


def test_matching_dates_are_silent():
    assert mapping.period_warnings(date(2026, 9, 9), "ДНР_статистика_на_09.09.2026.xlsx", None, TODAY) == []
    assert mapping.period_warnings(date(2026, 9, 15), "Ежедневный_отчет.xlsx", "15.09", TODAY) == []


def test_file_date_differs():
    ws = mapping.period_warnings(date(2026, 9, 2), "Показатели_MAX_09.09.2026.xlsx", None, TODAY)
    assert _codes(ws) == ["period_differs_from_file"]
    assert "09.09.2026" in ws[0]["message"] and "02.09.2026" in ws[0]["message"]


def test_iso_and_underscore_dates_are_read():
    assert mapping.file_name_dates("отчет_2026-08-19.xlsx") == [date(2026, 8, 19)]
    assert mapping.file_name_dates("forma_9_9_2026.xlsx") == [date(2026, 9, 9)]
    assert mapping.file_name_dates("Отчёт за август.xlsx") == []


def test_sheet_and_future():
    ws = mapping.period_warnings(date(2026, 10, 15), "отчет.xlsx", "15.09", TODAY)
    assert _codes(ws) == ["period_in_future", "period_differs_from_sheet"]


def test_no_period_no_warning():
    assert mapping.period_warnings(None, "x_09.09.2026.xlsx", "01.01", TODAY) == []


def test_book_for_a_period_accepts_any_date_inside_it():
    name = "Ежедневный_отчет_в_разрезе_отделов_и_услуг_с_12_01_по_15_09_2026.xlsx"
    assert mapping.file_name_range(name) == (date(2026, 1, 12), date(2026, 9, 15))
    assert mapping.period_warnings(date(2026, 3, 4), name, "04.03", TODAY) == []
    assert _codes(mapping.period_warnings(date(2026, 9, 20), name, None, TODAY)) == ["period_differs_from_file"]
