"""Валидация бизнес-правил при загрузке данных (чистая функция, без БД)."""
from app.modules.ingestion.mapping import _validate_grid

VF = [{"field_code": "kol", "column_index": 1}]
FT = {"kol": "number"}


def _codes(rows, label_col=0):
    return {w["code"] for w in _validate_grid(rows, VF, label_col, FT)}


def test_clean_grid_no_warnings():
    assert _validate_grid([["Паспорт", "10"], ["ИНН", "20"]], VF, 0, FT) == []


def test_duplicate_rows():
    assert "duplicate_rows" in _codes([["Паспорт", "10"], ["Паспорт", "20"]])


def test_empty_row_label():
    assert "empty_rows" in _codes([["", "10"], ["  ", "20"]])


def test_text_in_number_field():
    assert "not_a_number" in _codes([["Паспорт", "нет"]])


def test_negative_value():
    assert "negative" in _codes([["Паспорт", "-5"]])


def test_missing_number():
    assert "missing_values" in _codes([["Паспорт", ""]])


def test_multiple_warnings_together():
    codes = _codes([["Паспорт", "-5"], ["Паспорт", "abc"], ["", "3"]])
    assert {"duplicate_rows", "negative", "not_a_number", "empty_rows"} <= codes
