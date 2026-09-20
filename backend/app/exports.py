"""Утилиты выгрузки табличных данных в CSV и XLSX (для журналов/отчётов).

CSV: разделитель `;` и BOM UTF-8 — чтобы Excel (в т.ч. русская локаль) открыл
файл без «кракозябр» и без мастера импорта.

Здесь же — заголовок вложения: имена файлов в системе русские, и собрать его
правильно нужно ВЕЗДЕ, где отдаётся файл.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Iterable, Sequence
from urllib.parse import quote


def attachment_header(filename: str, fallback: str = "file") -> str:
    """Значение `Content-Disposition` для файла с РУССКИМ именем.

    В `filename=` можно только ASCII, поэтому по RFC 5987 отдаём оба варианта:
    ASCII-запасной для старых программ и `filename*` с ПРОЦЕНТНЫМ кодированием
    для остальных. Без `quote` сырая кириллица роняет отдачу файла целиком:
    заголовки кодируются latin-1, и ответ падает с UnicodeEncodeError —
    ровно это и случилось с приложенными руководствами.

    Из имени убираем то, что файловые системы не примут (слеши, двоеточия,
    кавычки), иначе браузер сохранит файл со сломанным именем или откажется.

    Русское имя целиком выпадает из ASCII, и запасной вариант превратился бы в
    «.docx» — скрытый файл без имени; поэтому пусто → осмысленный `fallback`.
    """
    clean = re.sub(r'[\\/:*?"<>|\r\n]+', " ", filename or "").strip() or fallback
    clean = clean[:120]
    stem, dot, ext = clean.rpartition(".")
    ascii_stem = (stem or clean).encode("ascii", "ignore").decode().strip()
    # От «Руководство_пользователя.docx» после отсева не-ASCII остаются одни
    # подчёркивания: «_.docx» — почти безымянный файл. Годным считаем только
    # остаток, где есть буква или цифра.
    if not re.search(r"[A-Za-z0-9]", ascii_stem):
        ascii_stem = ""
    ascii_name = f"{ascii_stem}.{ext}" if ascii_stem and dot else fallback
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(clean)}'


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
