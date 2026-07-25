"""Утилиты выгрузки табличных данных в CSV и XLSX (для журналов/отчётов).

CSV: разделитель `;` и BOM UTF-8 — чтобы Excel (в т.ч. русская локаль) открыл
файл без «кракозябр» и без мастера импорта.
"""
from __future__ import annotations

import csv
import io
from typing import Iterable, Sequence


def to_csv(headers: Sequence[str], rows: Iterable[Sequence]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(headers)
    for r in rows:
        w.writerow(["" if v is None else v for v in r])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def to_xlsx(sheet: str, headers: Sequence[str], rows: Iterable[Sequence]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = (sheet or "Лист")[:31]
    ws.append(list(headers))
    for r in rows:
        ws.append(["" if v is None else v for v in r])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
