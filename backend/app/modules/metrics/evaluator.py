"""Вычисление AST формулы на реальных данных через Resolver.

Resolver абстрагирует источник значений (в 4.2 — из dataset_values в PostgreSQL,
в тестах — из словаря в памяти), поэтому движок не зависит от БД.

Ядро (4.1): арифметика, агрегаты SUM/AVG/COUNT/MIN/MAX(+filter),
field/cell/metric, PLAN_FACT_DELTA/PLAN_FACT_PCT.
Оконные RUNNING_TOTAL/PERIOD_COMPARE/SHARE_OF_TOTAL требуют ряда по периодам —
разбираются в AST, но их вычисление подключается на этапе 4.2.
"""
from __future__ import annotations

import json
from calendar import monthrange
from datetime import date
from typing import Any, Dict, List, Optional, Protocol, Tuple

from .parser import FormulaError


def node_key(node: Dict[str, Any]) -> str:
    """Стабильный ключ узла AST — для сопоставления предзагруженного ряда окна."""
    return json.dumps(node, sort_keys=True, ensure_ascii=False)


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, monthrange(y, m)[1]))


def _shift_back(iso: str, unit: str) -> str:
    """Период на 1 единицу назад (для PERIOD_COMPARE)."""
    from datetime import timedelta
    d = date.fromisoformat(iso)
    if unit == "day":
        d = d - timedelta(days=1)
    elif unit == "week":
        d = d - timedelta(days=7)
    elif unit == "month":
        d = _add_months(d, -1)
    elif unit == "quarter":
        d = _add_months(d, -3)
    elif unit == "year":
        d = _add_months(d, -12)
    return d.isoformat()


def _nearest_value(series: List[Tuple[str, float]], target_iso: str) -> float:
    """Значение периода, ближайшего к target (для сравнения периодов)."""
    tgt = date.fromisoformat(target_iso)
    best = min(series, key=lambda pv: abs((date.fromisoformat(pv[0]) - tgt).days))
    return best[1]


class Resolver(Protocol):
    """Источник значений для формулы."""

    def column(self, dataset: str, field: str, filters: Optional[Dict[str, str]]) -> List[float]:
        """Числовые значения поля активного выпуска датасета (с необязательным фильтром по строкам)."""
        ...

    def cell(self, dataset: str, date: str, row: str, col: str) -> float:
        """Значение конкретной ячейки: выпуск за дату, строка по названию, столбец по коду."""
        ...

    def metric(self, code: str, version: Any) -> float:
        """Значение другой метрики (version: 'approved' | 'latest' | int)."""
        ...

    def window_series(self, key: str) -> List[Tuple[str, float]]:
        """Ряд (период_iso, значение) для оконной функции — по возрастанию периода."""
        ...


def _agg(fn: str, values: List[float]) -> float:
    if fn == "COUNT":
        return float(len(values))
    if not values:
        raise FormulaError(f"{fn}: нет данных для агрегации")
    if fn == "SUM":
        return float(sum(values))
    if fn == "AVG":
        return float(sum(values) / len(values))
    if fn == "MIN":
        return float(min(values))
    if fn == "MAX":
        return float(max(values))
    raise FormulaError(f"Неизвестный агрегат {fn}")


def evaluate(ast: Dict[str, Any], resolver: Resolver) -> float:
    """AST → число. Бросает FormulaError при ошибке вычисления."""
    t = ast.get("t")

    if t == "num":
        return float(ast["v"])
    if t == "neg":
        return -evaluate(ast["e"], resolver)
    if t == "bin":
        l = evaluate(ast["l"], resolver)
        r = evaluate(ast["r"], resolver)
        op = ast["op"]
        if op == "+":
            return l + r
        if op == "-":
            return l - r
        if op == "*":
            return l * r
        if op == "/":
            if r == 0:
                raise FormulaError("Деление на ноль")
            return l / r
        raise FormulaError(f"Неизвестная операция {op}")
    if t == "pow":
        return evaluate(ast["base"], resolver) ** evaluate(ast["exp"], resolver)

    if t == "agg":
        arg = ast["arg"]
        if arg.get("t") != "field":
            raise FormulaError("Агрегат (SUM/AVG/…) принимает только field('датасет','поле')")
        col = resolver.column(arg["dataset"], arg["field"], ast.get("filter"))
        return _agg(ast["fn"], col)

    if t == "field":
        col = resolver.column(ast["dataset"], ast["field"], None)
        if len(col) == 1:
            return col[0]
        if not col:
            raise FormulaError(f"field('{ast['dataset']}','{ast['field']}'): нет данных")
        raise FormulaError(
            f"field('{ast['dataset']}','{ast['field']}') содержит {len(col)} значений — "
            f"оберните в агрегат (SUM/AVG/…)"
        )

    if t == "cell":
        return resolver.cell(ast["dataset"], ast["date"], ast["row"], ast["col"])

    if t == "metric":
        return resolver.metric(ast["code"], ast["version"])

    if t == "plan_fact":
        plan = evaluate(ast["plan"], resolver)
        fact = evaluate(ast["fact"], resolver)
        if ast["fn"] == "PLAN_FACT_DELTA":
            return fact - plan
        # PLAN_FACT_PCT — выполнение плана в процентах
        if plan == 0:
            raise FormulaError("PLAN_FACT_PCT: плановое значение равно нулю")
        return fact / plan * 100.0

    if t == "percent_of":
        # PERCENT_OF(база, значение): база = 100%, ищем % значения от базы
        base = evaluate(ast["base"], resolver)
        value = evaluate(ast["value"], resolver)
        if base == 0:
            raise FormulaError("Процент: база (100%) равна нулю")
        return value / base * 100.0

    if t in ("running_total", "period_compare", "share"):
        getter = getattr(resolver, "window_series", None)
        if getter is None:
            # Резолвер без периодов (напр. in-memory смоук): вычисление недоступно.
            raise FormulaError(f"Оконная функция «{t}» требует ряд значений по периодам")
        series = getter(node_key(ast))  # [(период_iso, значение)] по возрастанию
        if not series:
            raise FormulaError(f"Оконная функция «{t}»: нет данных по периодам (нужны выпуски датасета за разные периоды)")
        if t == "running_total":
            # Нарастающий итог как скаляр = сумма по всем периодам до последнего.
            return float(sum(v for _, v in series))
        if t == "share":
            # Доля значения последнего периода в сумме по всем периодам, %.
            total = sum(v for _, v in series)
            if total == 0:
                raise FormulaError("SHARE_OF_TOTAL: сумма по периодам равна нулю")
            return series[-1][1] / total * 100.0
        # period_compare: последний период vs период на 1 unit назад
        if len(series) < 2:
            raise FormulaError("PERIOD_COMPARE: нужно минимум 2 периода данных")
        cur_period, cur = series[-1]
        prev = _nearest_value(series[:-1], _shift_back(cur_period, ast["unit"]))
        mode = ast.get("mode", "delta")
        if mode == "delta":
            return cur - prev
        if prev == 0:
            raise FormulaError("PERIOD_COMPARE: значение прошлого периода равно нулю")
        return cur / prev * 100.0 if mode == "pct" else cur / prev  # pct | ratio

    raise FormulaError(f"Неизвестный узел AST: {t}")
