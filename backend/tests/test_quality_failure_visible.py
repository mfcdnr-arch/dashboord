"""Сбой проверки качества не читается как «замечаний нет» (20.09.2026).

Проверки качества СОВЕТУЮТ, а не запрещают, поэтому сорваться они не вправе:
02.09.2026 деление на ноль в одном правиле обрушило 52 выпуска из 54. Тогда
вокруг них поставили страховку `except → return []`.

🔴 У страховки была названная тогда же цена, и она не была закрыта: пустой
список означает «замечаний нет». Сбой ОДНОГО из девяти правил молча отключал
все разом — модератор видел чистую панель, а авто-выпуск (условие
`if warnings: return`) считал данные проверенными и отправлял на дашборд.

Теперь сбой возвращается ЗАМЕЧАНИЕМ: человек видит, что проверок не было, а
авто-выпуск останавливается сам, потому что список не пуст.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app.modules.ingestion import mapping, quality


async def test_broken_rule_becomes_a_visible_warning(monkeypatch, ids):
    """Сломанное правило даёт замечание, а не тишину."""
    def boom(*a, **kw):
        raise ZeroDivisionError("division by zero")

    monkeypatch.setattr(quality, "check_release", boom)

    from app import db
    async with db.acquire() as conn:
        warnings = await mapping.quality_warnings(
            conn, ids["org"], code="ztest_qf", period="2026-09-01",
            rows=[["Строка", "10"]],
            fields=[{"field_code": "lbl", "field_name": "Строка", "column_index": 0,
                     "is_row_label": True, "data_type": "text"},
                    {"field_code": "val", "field_name": "Значение", "column_index": 1,
                     "data_type": "number"}],
            label_col=0)

    assert warnings, "🔴 сбой правила снова читается как «замечаний нет»"
    assert warnings[0]["code"] == "quality_checks_failed"
    msg = warnings[0]["message"]
    # Замечание обязано сказать ГЛАВНОЕ: данные не проверены. Без этого
    # человек примет его за обычное предупреждение к цифрам.
    assert "НЕ проверены" in msg or "не проверены" in msg
    assert "division by zero" in msg, "причина сбоя не названа — администратору нечего чинить"


async def test_auto_release_stops_when_checks_did_not_run(monkeypatch, ids):
    """Авто-выпуск останавливается: непроверенные данные на дашборд не уходят.

    Проверяется само УСЛОВИЕ остановки — что непустой список замечаний
    (в том числе о сбое) закрывает авто-выпуск."""
    def boom(*a, **kw):
        raise ValueError("правило сломалось")

    monkeypatch.setattr(quality, "check_release", boom)

    from app import db
    async with db.acquire() as conn:
        warnings = await mapping.quality_warnings(
            conn, ids["org"], code="ztest_qf2", period="2026-09-01",
            rows=[["Строка", "10"]],
            fields=[{"field_code": "lbl", "field_name": "Строка", "column_index": 0,
                     "is_row_label": True, "data_type": "text"},
                    {"field_code": "val", "field_name": "Значение", "column_index": 1,
                     "data_type": "number"}],
            label_col=0)
    # Ровно это условие стоит в `_auto_release`: `if warnings: return`.
    assert bool(warnings) is True, "авто-выпуск выпустил бы непроверенные данные"


def test_auto_release_still_guards_on_warnings():
    """Страж: условие остановки авто-выпуска не должно исчезнуть из кода.

    Замена `if warnings:` на что-то иное снова пропустит непроверенные данные,
    и заметить это можно будет только на боевых цифрах."""
    import inspect

    from app.modules.ingestion import service

    src = inspect.getsource(service._auto_release)
    assert "warnings = await _auto_quality" in src
    assert "if warnings:" in src, "авто-выпуск перестал останавливаться на замечаниях"


def test_missing_table_is_not_silence():
    """Второй молчаливый путь: таблицы нет — проверять нечем, но и выпускать нельзя."""
    import inspect

    from app.modules.ingestion import service

    src = inspect.getsource(service._auto_quality)
    head = src.split("if row is None:")[1].split("import json")[0]
    assert "quality_checks_failed" in head, \
        "отсутствие распознанной таблицы снова читается как «замечаний нет»"
