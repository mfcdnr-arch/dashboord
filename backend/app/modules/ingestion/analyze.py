"""Анализ распознанной таблицы: строки-шапки и типы столбцов.

Чистые функции над нормализованной сеткой (см. parsers.ParsedTable.rows).
Результат — предложение системы, которое пользователь правит вручную (док-06).
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import List, Optional

# Порядок важен: сначала более специфичные форматы дат.
_DATE_FORMATS = (
    "%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y",
    "%Y.%m.%d", "%m/%d/%Y", "%d.%m.%y",
)
_NUM_CLEAN_RE = re.compile(r"[\s  ]")  # пробелы, неразрывные пробелы (разряды)


@dataclass
class ColumnInfo:
    column_index: int
    source_header: str
    inferred_type: str  # 'number' | 'date' | 'text'
    confidence: float   # 0..1 — доля значений столбца, подходящих под тип


def _is_number(s: str) -> bool:
    if not s:
        return False
    t = _NUM_CLEAN_RE.sub("", s)
    t = t.replace("%", "")
    # десятичная запятая → точка (если запятая одна и точек нет)
    if t.count(",") == 1 and t.count(".") == 0:
        t = t.replace(",", ".")
    else:
        t = t.replace(",", "")  # запятая как разрядный разделитель
    if t in ("", "-", "+", ".", "-.", "+."):
        return False
    try:
        float(t)
        return True
    except ValueError:
        return False


def _is_date(s: str) -> bool:
    if not s:
        return False
    for fmt in _DATE_FORMATS:
        try:
            dt.datetime.strptime(s, fmt)
            return True
        except ValueError:
            continue
    return False


def infer_type(values: List[str]) -> tuple[str, float]:
    """Тип столбца по значениям (без учёта пустых). Возвращает (тип, уверенность)."""
    non_empty = [v for v in values if v.strip() != ""]
    if not non_empty:
        return "text", 0.0
    n = len(non_empty)
    n_num = sum(1 for v in non_empty if _is_number(v))
    n_date = sum(1 for v in non_empty if _is_date(v))
    # дата приоритетнее числа (годы-числа не должны маскировать даты)
    if n_date >= n_num and n_date / n >= 0.6:
        return "date", round(n_date / n, 4)
    if n_num / n >= 0.6:
        return "number", round(n_num / n, 4)
    return "text", round(1.0, 4)


def guess_header_rows(rows: List[List[str]]) -> int:
    """Сколько верхних строк — шапка. Эвристика: строки без чисел сверху."""
    if not rows:
        return 0
    header = 0
    for row in rows[: min(3, len(rows))]:  # максимум 3 «этажа» шапки
        has_number = any(_is_number(c) for c in row)
        if has_number:
            break
        header += 1
    return max(1, header) if len(rows) > 1 else 0


def _compose_header(header_rows: List[List[str]], col: int) -> str:
    """Многоэтажная шапка → составное имя столбца (док-06)."""
    parts: List[str] = []
    for hr in header_rows:
        val = hr[col].strip() if col < len(hr) else ""
        if val and val not in parts:
            parts.append(val)
    return " · ".join(parts)


def analyze_columns(rows: List[List[str]], header_rows: int) -> List[ColumnInfo]:
    """Метаданные столбцов: составной заголовок + тип по данным ниже шапки."""
    if not rows:
        return []
    width = max(len(r) for r in rows)
    headers = rows[:header_rows]
    data = rows[header_rows:]
    columns: List[ColumnInfo] = []
    for c in range(width):
        header = _compose_header(headers, c) if headers else ""
        if not header:
            header = f"Столбец {c + 1}"
        col_values = [row[c] if c < len(row) else "" for row in data]
        inferred, conf = infer_type(col_values)
        columns.append(
            ColumnInfo(column_index=c, source_header=header, inferred_type=inferred, confidence=conf)
        )
    return columns
