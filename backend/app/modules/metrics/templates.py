"""Готовые метрики (рецепты формул), 2026-08-09.

Заказчик: «добавь в меню метрики готовые метрики, которые можно применять —
к примеру "Процент", и таких столько, сколько сможешь предложить».

Смысл: чтобы завести показатель, не нужно знать язык формул. Пользователь
выбирает рецепт («Процент — сколько A составляет от B»), мышью указывает
столбцы, а формулу на DSL собирает система. Дальше метрика живёт как обычно:
черновик → проверена → одобрена другим сотрудником.

Здесь ТОЛЬКО то, что движок формул реально вычисляет (см. evaluator.py):
агрегаты SUM/AVG/MIN/MAX/COUNT, арифметика, PERCENT_OF, PLAN_FACT_PCT/DELTA
и оконные RUNNING_TOTAL/PERIOD_COMPARE/SHARE_OF_TOTAL. Рецепта на то, чего
движок не умеет, быть не должно — иначе пользователь соберёт метрику, которая
не посчитается.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .parser import FormulaError, parse

# kind входа:
#   field  — столбец датасета (датасет + поле), подставляется как АГРЕГАТ (agg)
#   metric — ссылка на другую метрику
#   number — число, вводится руками (цель, норматив, делитель)
TEMPLATES: List[Dict[str, Any]] = [
    # ── Итоги по столбцу ────────────────────────────────────────────────────
    {
        "code": "total_sum", "group": "Итоги", "name": "Сумма по столбцу", "unit": None,
        "description": "Складывает все значения столбца. Базовый показатель «сколько всего».",
        "example": "Всего обращений за результатом услуги",
        "inputs": [{"key": "a", "kind": "field", "agg": "SUM", "label": "Столбец"}],
        "formula": "{a}",
    },
    {
        "code": "average", "group": "Итоги", "name": "Среднее значение", "unit": None,
        "description": "Среднее по столбцу. Для долей и процентов складывать нельзя — только усреднять.",
        "example": "Средняя доля доставленных уведомлений по районам",
        "inputs": [{"key": "a", "kind": "field", "agg": "AVG", "label": "Столбец"}],
        "formula": "{a}",
    },
    {
        "code": "maximum", "group": "Итоги", "name": "Максимум", "unit": None,
        "description": "Наибольшее значение столбца — где пик нагрузки.",
        "example": "Максимум обращений среди районов",
        "inputs": [{"key": "a", "kind": "field", "agg": "MAX", "label": "Столбец"}],
        "formula": "{a}",
    },
    {
        "code": "minimum", "group": "Итоги", "name": "Минимум", "unit": None,
        "description": "Наименьшее значение столбца — где просадка.",
        "example": "Минимум записавшихся среди подразделений",
        "inputs": [{"key": "a", "kind": "field", "agg": "MIN", "label": "Столбец"}],
        "formula": "{a}",
    },
    {
        "code": "count_rows", "group": "Итоги", "name": "Количество строк", "unit": "шт",
        "description": "Сколько строк с данными в столбце — например, сколько подразделений отчиталось.",
        "example": "Число отчитавшихся подразделений",
        "inputs": [{"key": "a", "kind": "field", "agg": "COUNT", "label": "Столбец"}],
        "formula": "{a}",
    },

    # ── Доли и проценты ─────────────────────────────────────────────────────
    {
        "code": "percent_of", "group": "Доли и проценты", "name": "Процент (доля A от B)", "unit": "%",
        "description": "Сколько процентов одна величина составляет от другой. B — это 100 %.",
        "example": "Доля доставленных уведомлений от отправленных",
        "inputs": [
            {"key": "part", "kind": "field", "agg": "SUM", "label": "Часть (A)"},
            {"key": "base", "kind": "field", "agg": "SUM", "label": "База — это 100 % (B)"},
        ],
        "formula": "PERCENT_OF({base}, {part})",
    },
    {
        "code": "conversion", "group": "Доли и проценты", "name": "Конверсия (из A дошли до B), %", "unit": "%",
        "description": "Какая часть начавших дошла до результата. Тот же расчёт, что процент, но по смыслу — воронка.",
        "example": "Сколько процентов обратившихся записались на приём",
        "inputs": [
            {"key": "result", "kind": "field", "agg": "SUM", "label": "Дошли до результата (B)"},
            {"key": "start", "kind": "field", "agg": "SUM", "label": "Начали (A)"},
        ],
        "formula": "PERCENT_OF({start}, {result})",
    },
    {
        "code": "share_of_total", "group": "Доли и проценты", "name": "Доля периода в общем итоге, %", "unit": "%",
        "description": "Какую часть от суммы за все периоды даёт последний период.",
        "example": "Какая доля годовых обращений пришлась на последний месяц",
        "min_periods": 2,
        "inputs": [{"key": "a", "kind": "field", "agg": "SUM", "label": "Столбец"}],
        "formula": "SHARE_OF_TOTAL({a}, over='all')",
    },

    # ── План и факт ─────────────────────────────────────────────────────────
    {
        "code": "plan_fact_pct", "group": "План и факт", "name": "Выполнение плана, %", "unit": "%",
        "description": "Насколько факт закрывает план. 100 % — план выполнен ровно.",
        "example": "Выполнение плана по записавшимся к 1 сентября",
        "inputs": [
            {"key": "plan", "kind": "field", "agg": "SUM", "label": "План"},
            {"key": "fact", "kind": "field", "agg": "SUM", "label": "Факт"},
        ],
        "formula": "PLAN_FACT_PCT({plan}, {fact})",
    },
    {
        "code": "plan_fact_delta", "group": "План и факт", "name": "Отклонение от плана", "unit": None,
        "description": "Факт минус план в единицах показателя: со знаком «плюс» — перевыполнение.",
        "example": "На сколько записалось больше или меньше плана",
        "inputs": [
            {"key": "plan", "kind": "field", "agg": "SUM", "label": "План"},
            {"key": "fact", "kind": "field", "agg": "SUM", "label": "Факт"},
        ],
        "formula": "PLAN_FACT_DELTA({plan}, {fact})",
    },
    {
        "code": "plan_remainder", "group": "План и факт", "name": "Остаток до плана", "unit": None,
        "description": "Сколько ещё нужно сделать до плана. Отрицательное значение — план уже перевыполнен.",
        "example": "Сколько записей осталось набрать до 1 сентября",
        "inputs": [
            {"key": "plan", "kind": "field", "agg": "SUM", "label": "План"},
            {"key": "fact", "kind": "field", "agg": "SUM", "label": "Факт"},
        ],
        "formula": "{plan} - {fact}",
    },

    # ── Динамика ────────────────────────────────────────────────────────────
    {
        "code": "period_delta", "group": "Динамика", "name": "Прирост к прошлому периоду", "unit": None,
        "description": "На сколько единиц изменилось значение по сравнению с прошлым месяцем.",
        "example": "Прирост обращений к прошлому месяцу",
        "min_periods": 2,
        "inputs": [{"key": "a", "kind": "field", "agg": "SUM", "label": "Столбец"}],
        "formula": "PERIOD_COMPARE({a}, 'month')",
    },
    {
        "code": "period_pct", "group": "Динамика", "name": "Прирост к прошлому периоду, %", "unit": "%",
        "description": "Значение этого периода в процентах к прошлому: 104 % — рост на 4 %.",
        "example": "Динамика обращений месяц к месяцу",
        "min_periods": 2,
        "inputs": [{"key": "a", "kind": "field", "agg": "SUM", "label": "Столбец"}],
        "formula": "PERIOD_COMPARE({a}, 'month', mode='pct')",
    },
    {
        "code": "yoy", "group": "Динамика", "name": "Год к году, %", "unit": "%",
        "description": "Сравнение с тем же периодом прошлого года — снимает сезонность.",
        "example": "Обращения августа к августу прошлого года",
        "min_periods": 2,
        "inputs": [{"key": "a", "kind": "field", "agg": "SUM", "label": "Столбец"}],
        "formula": "PERIOD_COMPARE({a}, 'year', mode='pct')",
    },
    {
        "code": "running_total", "group": "Динамика", "name": "Накопительный итог", "unit": None,
        "description": "Сумма с начала наблюдений по последний период включительно.",
        "example": "Всего записавшихся с начала внедрения",
        "min_periods": 2,
        "inputs": [{"key": "a", "kind": "field", "agg": "SUM", "label": "Столбец"}],
        "formula": "RUNNING_TOTAL({a}, grain='month')",
    },

    # ── Сравнение и нормирование ────────────────────────────────────────────
    {
        "code": "difference", "group": "Сравнение", "name": "Разница A − B", "unit": None,
        "description": "Насколько один показатель больше другого. Например, сколько уведомлений не дошло.",
        "example": "Отправлено минус доставлено — потери",
        "inputs": [
            {"key": "a", "kind": "field", "agg": "SUM", "label": "Уменьшаемое (A)"},
            {"key": "b", "kind": "field", "agg": "SUM", "label": "Вычитаемое (B)"},
        ],
        "formula": "{a} - {b}",
    },
    {
        "code": "ratio", "group": "Сравнение", "name": "Во сколько раз A больше B", "unit": "раз",
        "description": "Отношение двух величин. Удобно, когда проценты неудобны — «в 3,2 раза».",
        "example": "Во сколько раз обращений больше, чем записей",
        "inputs": [
            {"key": "a", "kind": "field", "agg": "SUM", "label": "Числитель (A)"},
            {"key": "b", "kind": "field", "agg": "SUM", "label": "Знаменатель (B)"},
        ],
        "formula": "{a} / {b}",
    },
    {
        "code": "per_unit", "group": "Сравнение", "name": "В среднем на единицу", "unit": None,
        "description": "Показатель, делённый на число (сотрудников, окон, дней) — нагрузка на единицу.",
        "example": "Обращений в среднем на одно окно приёма",
        "inputs": [
            {"key": "a", "kind": "field", "agg": "SUM", "label": "Что делим"},
            {"key": "n", "kind": "number", "label": "На сколько делим", "hint": "например, число окон"},
        ],
        "formula": "{a} / {n}",
    },

    # ── Цели ────────────────────────────────────────────────────────────────
    {
        "code": "target_gap_pct", "group": "Цели", "name": "Отклонение от цели, %", "unit": "%",
        "description": "На сколько процентов показатель выше или ниже заданной цели.",
        "example": "Насколько доля доставленных отстаёт от целевых 95 %",
        "inputs": [
            {"key": "a", "kind": "field", "agg": "SUM", "label": "Показатель"},
            {"key": "target", "kind": "number", "label": "Цель", "hint": "например, 95"},
        ],
        "formula": "({a} - {target}) / {target} * 100",
    },
    {
        "code": "metric_percent", "group": "Цели", "name": "Процент между готовыми показателями", "unit": "%",
        "description": "То же, что «Процент», но берёт уже заведённые метрики, а не столбцы файла.",
        "example": "Доля доставленных от отправленных, если оба уже заведены как метрики",
        "inputs": [
            {"key": "part", "kind": "metric", "label": "Часть (A)"},
            {"key": "base", "kind": "metric", "label": "База — это 100 % (B)"},
        ],
        "formula": "PERCENT_OF({base}, {part})",
    },
]

BY_CODE = {t["code"]: t for t in TEMPLATES}


def _quote(v: str) -> str:
    """Строковый литерал DSL. Апостроф внутри имени поля сломал бы формулу."""
    return "'" + str(v).replace("'", "") + "'"


def _render_input(spec: Dict[str, Any], value: Any) -> str:
    kind = spec.get("kind", "field")
    if kind == "field":
        if not isinstance(value, dict) or not value.get("dataset_code") or not value.get("field"):
            raise FormulaError(f"«{spec['label']}»: выберите датасет и столбец")
        agg = spec.get("agg", "SUM")
        return f"{agg}(field({_quote(value['dataset_code'])},{_quote(value['field'])}))"
    if kind == "metric":
        code = value.get("metric_code") if isinstance(value, dict) else value
        if not code:
            raise FormulaError(f"«{spec['label']}»: выберите метрику")
        return f"metric({_quote(code)})"
    # number
    raw = value.get("number") if isinstance(value, dict) else value
    if raw is None or raw == "":
        raise FormulaError(f"«{spec['label']}»: введите число")
    try:
        num = float(raw)
    except (TypeError, ValueError):
        raise FormulaError(f"«{spec['label']}»: введите число") from None
    if num == 0 and spec["key"] in ("n", "target"):
        raise FormulaError(f"«{spec['label']}»: на ноль делить нельзя")
    return repr(num) if num != int(num) else str(int(num))


def build_formula(template_code: str, values: Dict[str, Any]) -> str:
    """Рецепт + выбранные пользователем столбцы → готовая формула DSL.

    Собранная формула сразу разбирается парсером: ошибку лучше показать здесь,
    рядом с полями ввода, чем при сохранении версии.
    """
    tpl = BY_CODE.get(template_code)
    if tpl is None:
        raise FormulaError(f"Неизвестный рецепт «{template_code}»")
    formula = tpl["formula"]
    for spec in tpl["inputs"]:
        formula = formula.replace("{" + spec["key"] + "}", _render_input(spec, values.get(spec["key"])))
    parse(formula)  # проверка, что получилось разбираемое выражение
    return formula


def suggested_name(template_code: str, labels: Dict[str, str]) -> Optional[str]:
    """Черновое название метрики из рецепта и подписей выбранных столбцов."""
    tpl = BY_CODE.get(template_code)
    if tpl is None:
        return None
    parts = [labels.get(s["key"], "") for s in tpl["inputs"] if s.get("kind") == "field"]
    parts = [p for p in parts if p]
    if not parts:
        return tpl["name"]
    if len(parts) == 1:
        return f"{tpl['name']}: {parts[0]}"
    return f"{tpl['name']}: {parts[0]} / {parts[1]}"
