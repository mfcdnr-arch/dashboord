"""Подсчёт строк формы: «сколько вопросов в работе», «сколько особо значимых».

До 08.10.2026 все виды виджетов работали с ЧИСЛОВЫМИ графами: складывали,
усредняли, делили план на факт. Формы, где главное — записи, а не числа
(реестр проблемных вопросов, итоги и планы недели в отчёте МФЦ для
Минэкономразвития), получали на дашборде одни таблицы: посчитать строки по
значению графы не умел ни один вид.

Подсчёт — не новый вид, а РЕЖИМ существующих (`config.count = true`): карточка
показывает число строк, столбики и круговая — число строк по значениям графы,
тепловая карта — по двум графам (матрица рисков «вероятность × влияние»).
Отрисовка, выгрузка в Excel, подсказка ⓘ и раскладка у видов уже есть, и
второй их копии под подсчёт не появляется. Таблица из того же модуля берёт
только отбор строк (`where`) — «лента особо значимых».

Строка формы — это `row_index` выпуска, у которой есть хоть одно значение:
пустые строки бланка в выпуск не попадают и не считаются. Права на строки и
фильтр строки страницы действуют так же, как у остальных видов, — подсчёт не
вправе стать обходным путём к строкам, которых человеку видеть нельзя.

Условия отбора (`where`, все сразу — «И»): {field, op, value}
  eq / ne       — равно / не равно (без учёта регистра, «ё» = «е», 5 = «5»);
  in            — одно из значений списка;
  contains      — содержит текст;
  gt/gte/lt/lte — сравнение чисел;
  filled/empty  — графа заполнена / пуста;
  date_before_report — дата в графе раньше отчётной даты выпуска («срок истёк
    на дату отчёта»). Отсчёт от даты ОТЧЁТА, а не от сегодняшнего дня: старый
    отчёт должен показывать то, что было просрочено тогда, а не сейчас.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

from ..metrics import resolver as mr
from ._base import DashboardError

OPS = ("eq", "ne", "in", "contains", "gt", "gte", "lt", "lte", "filled", "empty", "date_before_report")
EMPTY_LABEL = "— не заполнено"
# Больше значений на оси матрицы — это уже не матрица, а простыня: такой
# подсчёт честнее показать столбиками или таблицей.
MAX_AXIS = 30

_DATE_RES = (
    (re.compile(r"(\d{4})-(\d{2})-(\d{2})"), ("y", "m", "d")),
    (re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})"), ("d", "m", "y")),
)


def _norm(v) -> str:
    """Значение для сравнения: регистр, «ё», лишние пробелы и «5.0» не различают."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip().casefold().replace("ё", "е")
    s = re.sub(r"\s+", " ", s)
    # «5,0» и «5» — одно значение шкалы.
    m = re.fullmatch(r"(-?\d+)[.,]0+", s)
    return m.group(1) if m else s


def _label(v) -> str:
    """Подпись значения на оси: целое без «.0», текст как в форме."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return EMPTY_LABEL
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else f"{v:g}".replace(".", ",")
    return re.sub(r"\s+", " ", str(v).strip())


def _num(v) -> Optional[float]:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(" ", "").replace(" ", "").replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return None
    return None


def parse_date(v) -> Optional[date]:
    """Первая дата в значении: «2026-10-06 00:00:00», «До 13.10.2026», «13.10.2026»."""
    if v is None:
        return None
    s = str(v)
    for rx, order in _DATE_RES:
        m = rx.search(s)
        if m:
            parts = dict(zip(order, m.groups(), strict=False))
            try:
                return date(int(parts["y"]), int(parts["m"]), int(parts["d"]))
            except ValueError:
                return None
    return None


def check_where(where) -> List[dict]:
    """Условия из конфигурации — проверенные. Ошибку в условии говорим словами:
    молча пропущенное условие дало бы правдоподобное, но неверное число."""
    out: List[dict] = []
    for c in where or []:
        if not isinstance(c, dict) or not c.get("field"):
            raise DashboardError("Подсчёт: у условия не указана графа")
        op = c.get("op") or "eq"
        if op not in OPS:
            raise DashboardError(f"Подсчёт: неизвестное условие «{op}»")
        if op in ("gt", "gte", "lt", "lte") and _num(c.get("value")) is None:
            raise DashboardError(f"Подсчёт: для сравнения «{op}» нужно число")
        if op == "in" and not isinstance(c.get("value"), list):
            raise DashboardError("Подсчёт: для условия «одно из» нужен список значений")
        out.append({"field": c["field"], "op": op, "value": c.get("value")})
    return out


def _match(cond: dict, v, report_day: Optional[date], unparsed: List[int]) -> bool:
    op, want = cond["op"], cond.get("value")
    if op == "filled":
        return _norm(v) != ""
    if op == "empty":
        return _norm(v) == ""
    if op == "eq":
        return _norm(v) == _norm(want)
    if op == "ne":
        return _norm(v) != _norm(want)
    if op == "in":
        return _norm(v) in {_norm(x) for x in (want or [])}
    if op == "contains":
        return _norm(want) in _norm(v) if _norm(want) else True
    if op in ("gt", "gte", "lt", "lte"):
        a, b = _num(v), _num(want)
        if a is None or b is None:
            return False
        return {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[op]
    if op == "date_before_report":
        if _norm(v) == "":
            return False
        d = parse_date(v)
        if d is None:
            unparsed.append(1)
            return False
        return report_day is not None and d < report_day
    return False


async def _release(conn, org_id, code: str, period) -> Tuple[object, Optional[date]]:
    rel = await mr._active_release(conn, org_id, code, period)
    if rel is None:
        raise DashboardError(f"Датасет '{code}' не найден или не выпущен")
    day = await conn.fetchval("select reporting_period_start from dataset_releases where id=$1", rel)
    return rel, day


async def _rows(conn, release_id, fields: Sequence[str], row=None, allowed=None) -> Dict[int, dict]:
    """Строки выпуска: {row_index: {графа: значение}} — только нужные графы."""
    params: list = [release_id, row]
    acl = ""
    if allowed is not None:
        params.append(list(allowed))
        acl = f" and row_label = any(${len(params)}::text[])"
    present = await conn.fetch(
        "select distinct row_index from dataset_values where dataset_release_id=$1 "
        f"and ($2::text is null or row_label=$2){acl}", *params)
    rows: Dict[int, dict] = {r["row_index"]: {} for r in present}
    if fields and rows:
        params.append(list(fields))
        vals = await conn.fetch(
            "select row_index, canonical_field_code as f, value_text, value_number from dataset_values "
            f"where dataset_release_id=$1 and ($2::text is null or row_label=$2){acl} "
            f"and canonical_field_code = any(${len(params)}::text[])", *params)
        for v in vals:
            rows.setdefault(v["row_index"], {})[v["f"]] = (
                float(v["value_number"]) if v["value_number"] is not None else v["value_text"])
    return rows


async def _titles(conn, release_id, codes: Sequence[str]) -> Dict[str, str]:
    """Имена граф-осей: на матрице рисков оси подписаны «Вероятность» и
    «Влияние», а не кодом поля."""
    rows = await conn.fetch(
        "select cf.code, cf.name from canonical_fields cf join dataset_releases r "
        "on r.object_id = cf.object_id where r.id=$1 and cf.code = any($2::text[])",
        release_id, [c for c in codes if c])
    return {r["code"]: r["name"] for r in rows}


def _filter(rows: Dict[int, dict], where: List[dict], report_day) -> Tuple[List[int], int]:
    unparsed: List[int] = []
    keep = [i for i, r in sorted(rows.items())
            if all(_match(c, r.get(c["field"]), report_day, unparsed) for c in where)]
    return keep, len(unparsed)


def _axis(values: List, fixed: Optional[list]) -> List[str]:
    """Порядок значений оси. Заданный человеком (шкала «1–5») — как есть и
    целиком, даже с нулями: пустая клетка матрицы рисков — тоже ответ. Иначе
    числа по возрастанию, текст — по убыванию частоты."""
    if fixed:
        return [_label(x) for x in fixed]
    labels = [_label(v) for v in values]
    uniq = list(dict.fromkeys(labels))
    if uniq and all(_num(x) is not None for x in uniq if x != EMPTY_LABEL):
        nums = sorted((x for x in uniq if x != EMPTY_LABEL), key=lambda x: _num(x) or 0)
        return nums + ([EMPTY_LABEL] if EMPTY_LABEL in uniq else [])
    freq = {x: labels.count(x) for x in uniq}
    return sorted(uniq, key=lambda x: (x == EMPTY_LABEL, -freq[x], x))


def _note(unparsed: int, outside: int = 0) -> Optional[str]:
    """Оговорки подсчёта словами. Строка, которую подсчёт не учёл, не должна
    пропадать молча: иначе «5 вопросов» читается как «всего 5»."""
    parts = []
    if unparsed:
        parts.append(f"У {unparsed} строк дата не распознана (например, «на постоянной основе») — "
                     "в подсчёт по сроку они не вошли.")
    if outside:
        parts.append(f"{outside} строк со значением вне заданной шкалы не показаны.")
    return " ".join(parts) or None


async def count_value(conn, org_id, cfg: dict, period=None, row=None, allowed=None) -> dict:
    """Карточка: сколько строк подходит под условия."""
    code = _code(cfg)
    where = check_where(cfg.get("where"))
    rel, day = await _release(conn, org_id, code, period)
    rows = await _rows(conn, rel, [c["field"] for c in where], row, allowed)
    keep, unparsed = _filter(rows, where, day)
    return {"value": float(len(keep)), "rows_total": len(rows), "note": _note(unparsed)}


async def count_series(conn, org_id, cfg: dict, to_date=None, row=None, allowed=None) -> List[tuple]:
    """Число подходящих строк по каждому отчёту — для прироста и мини-графика."""
    code = _code(cfg)
    where = check_where(cfg.get("where"))
    rels = await conn.fetch(
        "select id, reporting_period_start as p from dataset_releases "
        "where organization_id=$1 and code=$2 and status <> 'superseded' "
        "and ($3::text is null or reporting_period_start <= $3::text::date) "
        "order by reporting_period_start nulls last", org_id, code, to_date)
    out = []
    for r in rels:
        rows = await _rows(conn, r["id"], [c["field"] for c in where], row, allowed)
        keep, _ = _filter(rows, where, r["p"])
        out.append((r["p"].isoformat() if r["p"] else None, float(len(keep))))
    return out


async def count_by(conn, org_id, cfg: dict, period=None, row=None, allowed=None) -> dict:
    """Столбики и круговая: число строк по значениям графы `group_by`."""
    code, field = _code(cfg), cfg.get("group_by")
    if not field:
        raise DashboardError("Подсчёт по значениям: укажите графу (group_by)")
    where = check_where(cfg.get("where"))
    rel, day = await _release(conn, org_id, code, period)
    rows = await _rows(conn, rel, [field] + [c["field"] for c in where], row, allowed)
    keep, unparsed = _filter(rows, where, day)
    axis = _axis([rows[i].get(field) for i in keep], cfg.get("group_values"))
    counts = {a: 0 for a in axis}
    outside = 0
    for i in keep:
        lab = _label(rows[i].get(field))
        if lab in counts:
            counts[lab] += 1
        else:
            outside += 1
    names = await _titles(conn, rel, [field])
    return {"categories": axis, "values": [float(counts[a]) for a in axis],
            "group_title": names.get(field, field), "note": _note(unparsed, outside)}


async def count_matrix(conn, org_id, cfg: dict, period=None, row=None, allowed=None) -> dict:
    """Тепловая карта: число строк по паре графы × графа (матрица рисков)."""
    code, f1, f2 = _code(cfg), cfg.get("group_by"), cfg.get("group_by2")
    if not f1 or not f2:
        raise DashboardError("Матрица подсчёта: укажите две графы (group_by и group_by2)")
    where = check_where(cfg.get("where"))
    rel, day = await _release(conn, org_id, code, period)
    rows = await _rows(conn, rel, [f1, f2] + [c["field"] for c in where], row, allowed)
    keep, unparsed = _filter(rows, where, day)
    ys = _axis([rows[i].get(f1) for i in keep], cfg.get("group_values"))
    xs = _axis([rows[i].get(f2) for i in keep], cfg.get("group_values2"))
    if len(ys) > MAX_AXIS or len(xs) > MAX_AXIS:
        raise DashboardError(
            f"Матрица подсчёта: у графы больше {MAX_AXIS} значений — это уже не матрица. "
            "Покажите подсчёт столбиками или таблицей.")
    grid = {(y, x): 0 for y in ys for x in xs}
    outside = 0
    for i in keep:
        k = (_label(rows[i].get(f1)), _label(rows[i].get(f2)))
        if k in grid:
            grid[k] += 1
        else:
            outside += 1
    cells = [[xi, yi, float(grid[(y, x)])] for yi, y in enumerate(ys) for xi, x in enumerate(xs)]
    nums = [c[2] for c in cells]
    names = await _titles(conn, rel, [f1, f2])
    return {"rows": ys, "columns": xs, "cells": cells,
            "row_title": names.get(f1, f1), "col_title": names.get(f2, f2),
            "min": min(nums) if nums else 0, "max": max(nums) if nums else 0,
            "note": _note(unparsed, outside), "count": True}


async def matching_rows(conn, release_id, where, report_day, row=None, allowed=None) -> set:
    """Номера строк выпуска, подходящих под условия, — отбор строк таблицы."""
    conds = check_where(where)
    rows = await _rows(conn, release_id, [c["field"] for c in conds], row, allowed)
    keep, _ = _filter(rows, conds, report_day)
    return set(keep)


def _code(cfg: dict) -> str:
    if not cfg.get("dataset_code"):
        raise DashboardError("Подсчёт: укажите форму (dataset_code)")
    return cfg["dataset_code"]


# Слова для подсказки ⓘ и подписи — одни на экран и на пояснение.
_OP_WORDS = {"eq": "равно", "ne": "не равно", "in": "одно из", "contains": "содержит",
             "gt": "больше", "gte": "не меньше", "lt": "меньше", "lte": "не больше",
             "filled": "заполнена", "empty": "пуста", "date_before_report": "срок истёк на дату отчёта"}


def describe_where(where, name_of) -> str:
    """«где «Статус» равно «В работе» и «Срок» — срок истёк на дату отчёта»."""
    parts = []
    for c in where or []:
        op = c.get("op") or "eq"
        f = f"«{name_of(c.get('field'))}»"
        if op in ("filled", "empty"):
            parts.append(f"{f} {_OP_WORDS[op]}")
        elif op == "date_before_report":
            parts.append(f"по графе {f} {_OP_WORDS[op]}")
        elif op == "in":
            vals = ", ".join(f"«{_label(v)}»" for v in (c.get("value") or []))
            parts.append(f"{f} — {_OP_WORDS[op]}: {vals}")
        else:
            parts.append(f"{f} {_OP_WORDS.get(op, op)} «{_label(c.get('value'))}»")
    return ("где " + " и ".join(parts)) if parts else ""
