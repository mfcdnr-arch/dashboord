"""Источник данных для формул из dataset_values (PostgreSQL) + вычисление.

Вычислитель (evaluator) синхронный, asyncpg — асинхронный, поэтому применяем
предзагрузку: обходим AST, собираем все ссылки (field/cell/metric), асинхронно
достаём их значения в кэш, затем синхронно вычисляем формулу по кэшу.

Ссылки на данные (по коду датасета — берётся АКТИВНЫЙ, не superseded, выпуск):
- field('код','поле')        → столбец поля последнего активного выпуска датасета;
- cell('код', date, row, col) → значение выпуска ЗА ДАТУ: строка по row_label, столбец по коду;
- metric('код', version)      → значение другой метрики (рекурсивно, с защитой от циклов).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from . import evaluator
from .parser import FormulaError


# --------------------------------------------------------------------------- #
# Сбор ссылок из AST (для предзагрузки)
# --------------------------------------------------------------------------- #
def collect_refs(ast: Dict[str, Any]) -> Dict[str, list]:
    columns: List[Tuple[str, str, Optional[Dict[str, str]]]] = []
    cells: List[Tuple[str, str, str, str]] = []
    metrics: List[Tuple[str, Any]] = []
    windows: List[Dict[str, Any]] = []

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        t = node.get("t")
        if t in ("running_total", "period_compare", "share"):
            # Оконная функция — данные грузятся отдельно по периодам (не рекурсируем в arg).
            windows.append(node)
            return
        if t == "agg" and node["arg"].get("t") == "field":
            f = node["arg"]
            columns.append((f["dataset"], f["field"], node.get("filter")))
        elif t == "field":
            columns.append((node["dataset"], node["field"], None))
        elif t == "cell":
            cells.append((node["dataset"], node["date"], node["row"], node["col"]))
        elif t == "metric":
            metrics.append((node["code"], node["version"]))
        for val in node.values():
            if isinstance(val, dict):
                walk(val)
            elif isinstance(val, list):
                for it in val:
                    walk(it)

    walk(ast)
    return {"columns": columns, "cells": cells, "metrics": metrics, "windows": windows}


# --------------------------------------------------------------------------- #
# Кэш-резолвер (реализует протокол evaluator.Resolver)
# --------------------------------------------------------------------------- #
class CacheResolver:
    def __init__(self, columns: dict, cells: dict, metrics: dict, windows: Optional[dict] = None):
        self._columns = columns
        self._cells = cells
        self._metrics = metrics
        self._windows = windows or {}

    def window_series(self, key: str):
        if key not in self._windows:
            raise FormulaError("Оконная функция: ряд по периодам не предзагружен")
        return self._windows[key]

    def column(self, dataset: str, field: str, filters: Optional[Dict[str, str]]) -> List[float]:
        key = (dataset, field, _freeze(filters))
        if key not in self._columns:
            raise FormulaError(f"Нет данных: field('{dataset}','{field}')")
        return self._columns[key]

    def cell(self, dataset: str, date: str, row: str, col: str) -> float:
        key = (dataset, date, row, col)
        if key not in self._cells:
            raise FormulaError(f"Нет ячейки: cell('{dataset}', date='{date}', row='{row}', col='{col}')")
        return self._cells[key]

    def metric(self, code: str, version: Any) -> float:
        if code not in self._metrics:
            raise FormulaError(f"Нет метрики: metric('{code}')")
        return self._metrics[code]


def _freeze(filters: Optional[Dict[str, str]]):
    return tuple(sorted(filters.items())) if filters else None


# --------------------------------------------------------------------------- #
# Доступ к БД
# --------------------------------------------------------------------------- #
async def _active_release(conn, org_id, code: str, date: Optional[str] = None):
    """id активного (не superseded) выпуска датасета. Без даты — последний по периоду."""
    if date is not None:
        return await conn.fetchval(
            "select id from dataset_releases where organization_id=$1 and code=$2 "
            "and status <> 'superseded' and reporting_period_start = $3::text::date "
            "order by created_at desc limit 1",
            org_id, code, date,
        )
    return await conn.fetchval(
        "select id from dataset_releases where organization_id=$1 and code=$2 "
        "and status <> 'superseded' "
        "order by reporting_period_start desc nulls last, created_at desc limit 1",
        org_id, code,
    )


async def _dataset_periods(conn, org_id, datasets) -> List[str]:
    """Упорядоченный список периодов (reporting_period_start, iso) по выпускам
    указанных датасетов — ось времени для оконных функций."""
    if not datasets:
        return []
    rows = await conn.fetch(
        "select distinct reporting_period_start as p from dataset_releases "
        "where organization_id=$1 and code = any($2::text[]) and status <> 'superseded' "
        "and reporting_period_start is not null order by p", org_id, list(datasets))
    return [r["p"].isoformat() for r in rows]


async def _fetch_column(conn, org_id, dataset: str, field: str, filters: Optional[Dict[str, str]],
                        period: Optional[str] = None) -> List[float]:
    rel = await _active_release(conn, org_id, dataset, period)
    if rel is None:
        raise FormulaError(f"Датасет '{dataset}' не найден или не выпущен")
    if filters:
        # фильтр выбирает строки по названию (row_label) — по значению условия
        rows = await conn.fetch(
            "select value_number from dataset_values "
            "where dataset_release_id=$1 and canonical_field_code=$2 "
            "and row_label = any($3::text[]) and value_number is not null order by row_index",
            rel, field, list(filters.values()),
        )
    else:
        rows = await conn.fetch(
            "select value_number from dataset_values "
            "where dataset_release_id=$1 and canonical_field_code=$2 "
            "and value_number is not null order by row_index",
            rel, field,
        )
    return [float(r["value_number"]) for r in rows]


async def _fetch_cell(conn, org_id, dataset: str, date: str, row: str, col: str) -> float:
    rel = await _active_release(conn, org_id, dataset, date)
    if rel is None:
        raise FormulaError(f"Нет выпуска датасета '{dataset}' за {date}")
    val = await conn.fetchval(
        "select value_number from dataset_values "
        "where dataset_release_id=$1 and row_label=$2 and canonical_field_code=$3 "
        "and value_number is not null limit 1",
        rel, row, col,
    )
    if val is None:
        raise FormulaError(f"Нет числового значения: cell('{dataset}', date='{date}', row='{row}', col='{col}')")
    return float(val)


# --------------------------------------------------------------------------- #
# Публичное API: вычислить AST на реальных данных
# --------------------------------------------------------------------------- #
async def evaluate_ast(conn, org_id, ast: Dict[str, Any], _visiting: Optional[set] = None) -> float:
    """Предзагрузка ссылок из БД → синхронное вычисление формулы."""
    _visiting = _visiting or set()
    refs = collect_refs(ast)

    columns: dict = {}
    for dataset, field, filt in refs["columns"]:
        col_key = (dataset, field, _freeze(filt))
        if col_key not in columns:
            columns[col_key] = await _fetch_column(conn, org_id, dataset, field, filt)

    cells: dict = {}
    for dataset, date, row, col in refs["cells"]:
        cell_key = (dataset, date, row, col)
        if cell_key not in cells:
            cells[cell_key] = await _fetch_cell(conn, org_id, dataset, date, row, col)

    metrics: dict = {}
    for code, version in refs["metrics"]:
        if code not in metrics:
            metrics[code] = await _compute_metric(conn, org_id, code, version, _visiting)

    windows: dict = {}
    for wnode in refs.get("windows", []):
        window_key = evaluator.node_key(wnode)
        if window_key not in windows:
            windows[window_key] = await _compute_window_series(conn, org_id, wnode, _visiting)

    resolver = CacheResolver(columns, cells, metrics, windows)
    return evaluator.evaluate(ast, resolver)


async def evaluate_series(conn, org_id, ast: Dict[str, Any]) -> List[Tuple[str, float]]:
    """Значение формулы по КАЖДОМУ отчётному периоду: [(период, значение), …].

    `evaluate_ast` считает только на последнем выпуске и отвечает на вопрос
    «сколько сейчас». Здесь — «как менялось», ради прироста к прошлому отчёту
    на карточке «Главной».

    Своей логики не заводим: ровно тот же обход, которым уже считаются оконные
    функции (PERIOD_COMPARE, RUNNING_TOTAL). Иначе прирост на карточке и
    прирост внутри формулы однажды разошлись бы.
    """
    return await _compute_window_series(conn, org_id, {"arg": ast}, set())


async def _compute_window_series(conn, org_id, wnode: Dict[str, Any], visiting: set) -> List[Tuple[str, float]]:
    """Ряд (период, значение_arg) — вычисляет arg оконной функции для каждого
    периода выпусков датасетов, на которые ссылается arg. metric()/cell() внутри
    arg берутся на активном выпуске (период-независимо)."""
    arg = wnode["arg"]
    arg_refs = collect_refs(arg)
    datasets = {ds for ds, _f, _flt in arg_refs["columns"]}
    periods = await _dataset_periods(conn, org_id, datasets)

    # период-независимые ссылки (ячейки/метрики) — грузим один раз
    cells: dict = {}
    for ds, dt, row, col in arg_refs["cells"]:
        cells[(ds, dt, row, col)] = await _fetch_cell(conn, org_id, ds, dt, row, col)
    metrics: dict = {}
    for code, version in arg_refs["metrics"]:
        if code not in metrics:
            metrics[code] = await _compute_metric(conn, org_id, code, version, visiting)

    series: List[Tuple[str, float]] = []
    for p in periods:
        cols: dict = {}
        ok = True
        for ds, f, flt in arg_refs["columns"]:
            k = (ds, f, _freeze(flt))
            if k in cols:
                continue
            try:
                cols[k] = await _fetch_column(conn, org_id, ds, f, flt, period=p)
            except FormulaError:
                ok = False
                break
        if not ok:
            continue
        try:
            val = evaluator.evaluate(arg, CacheResolver(cols, cells, metrics))
        except FormulaError:
            continue
        series.append((p, val))
    return series


async def _compute_metric(conn, org_id, code: str, version: Any, visiting: set) -> float:
    if code in visiting:
        raise FormulaError(f"Циклическая зависимость через metric('{code}')")
    row = await _resolve_metric_version(conn, org_id, code, version)
    if row is None:
        raise FormulaError(f"Метрика '{code}' (version={version}) не найдена")
    import json
    ast = row["formula_ast"]
    if isinstance(ast, str):
        ast = json.loads(ast)
    return await evaluate_ast(conn, org_id, ast, visiting | {code})


async def _resolve_metric_version(conn, org_id, code: str, version: Any):
    base = (
        "select mv.formula_ast from metrics m "
        "join metric_versions mv on mv.metric_id = m.id "
        "where m.organization_id=$1 and m.code=$2 "
    )
    if version == "approved":
        return await conn.fetchrow(base + "and mv.status='approved' order by mv.version_no desc limit 1", org_id, code)
    if version == "latest":
        return await conn.fetchrow(base + "order by mv.version_no desc limit 1", org_id, code)
    return await conn.fetchrow(base + "and mv.version_no=$3 limit 1", org_id, code, int(version))
