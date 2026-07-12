"""Форматные парсеры документов.

Каждый парсер принимает байты файла и возвращает `ParseResult` — список
нормализованных таблиц (сетка строк, ячейки как строки) + предупреждения.
Никакого ввода-вывода и обращений к БД: чистая обработка байтов, легко тестировать.

Форматы v1 (док-06): Excel (.xlsx/.xls), CSV, Word (.docx), PDF (текстовый слой).
OCR не поддерживается: для PDF без текста возвращаем предупреждение.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
from dataclasses import dataclass, field
from typing import List, Optional


class UnsupportedFormat(Exception):
    """Формат файла не поддерживается парсером."""


@dataclass
class ParsedTable:
    """Одна распознанная табличная область (лист/страница)."""

    sheet_or_page: Optional[str]
    table_index: int
    rows: List[List[str]]  # все строки, включая шапку; ячейки — строки ("" если пусто)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def column_count(self) -> int:
        return max((len(r) for r in self.rows), default=0)


@dataclass
class ParseResult:
    tables: List[ParsedTable] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Нормализация значений ячеек
# --------------------------------------------------------------------------- #
def _cell_to_str(value) -> str:
    """Приводит значение ячейки к строке (устойчиво к типам Excel/дат)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, (dt.datetime,)):
        # полночь → только дата, иначе дата+время
        if value.hour == 0 and value.minute == 0 and value.second == 0:
            return value.date().isoformat()
        return value.isoformat(sep=" ")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, float):
        # целочисленные float без хвоста ".0"
        if value.is_integer():
            return str(int(value))
        return repr(value)
    return str(value).strip()


def _normalize_grid(grid: List[List]) -> List[List[str]]:
    """Строки → строковые ячейки; обрезает полностью пустые хвостовые строки/столбцы."""
    rows = [[_cell_to_str(c) for c in row] for row in grid]
    # выравниваем по максимальной ширине
    width = max((len(r) for r in rows), default=0)
    rows = [r + [""] * (width - len(r)) for r in rows]
    # убрать хвостовые пустые столбцы
    while width > 0 and all(r[width - 1] == "" for r in rows):
        for r in rows:
            r.pop()
        width -= 1
    # убрать полностью пустые строки (строки-разделители — по док-06 игнорируем)
    rows = [r for r in rows if any(c != "" for c in r)]
    return rows


# --------------------------------------------------------------------------- #
# Excel .xlsx (openpyxl)
# --------------------------------------------------------------------------- #
def parse_xlsx(content: bytes) -> ParseResult:
    from openpyxl import load_workbook

    result = ParseResult()
    wb = load_workbook(io.BytesIO(content), read_only=False, data_only=True)
    try:
        for idx, ws in enumerate(wb.worksheets):
            grid = [list(row) for row in ws.iter_rows(values_only=True)]
            grid = _fill_merged_xlsx(ws, grid)
            rows = _normalize_grid(grid)
            if rows:
                result.tables.append(
                    ParsedTable(sheet_or_page=ws.title, table_index=idx, rows=rows)
                )
        if not result.tables:
            result.warnings.append("В книге Excel не найдено непустых листов.")
    finally:
        wb.close()
    return result


def _fill_merged_xlsx(ws, grid: List[List]) -> List[List]:
    """Растиражировать значение объединённой ячейки на весь диапазон (док-06)."""
    for rng in ws.merged_cells.ranges:
        top_left = grid[rng.min_row - 1][rng.min_col - 1] if grid else None
        for r in range(rng.min_row - 1, rng.max_row):
            for c in range(rng.min_col - 1, rng.max_col):
                if r < len(grid) and c < len(grid[r]):
                    grid[r][c] = top_left
    return grid


# --------------------------------------------------------------------------- #
# Excel .xls (xlrd)
# --------------------------------------------------------------------------- #
def parse_xls(content: bytes) -> ParseResult:
    import xlrd

    result = ParseResult()
    book = xlrd.open_workbook(file_contents=content)
    for idx in range(book.nsheets):
        sheet = book.sheet_by_index(idx)
        grid: List[List] = []
        for r in range(sheet.nrows):
            grid.append([_xls_cell(book, sheet.cell(r, c)) for c in range(sheet.ncols)])
        rows = _normalize_grid(grid)
        if rows:
            result.tables.append(
                ParsedTable(sheet_or_page=sheet.name, table_index=idx, rows=rows)
            )
    if not result.tables:
        result.warnings.append("В книге Excel (.xls) не найдено непустых листов.")
    return result


def _xls_cell(book, cell):
    import xlrd

    if cell.ctype == xlrd.XL_CELL_DATE:
        try:
            return dt.datetime(*xlrd.xldate_as_tuple(cell.value, book.datemode))
        except Exception:
            return cell.value
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return bool(cell.value)
    return cell.value


# --------------------------------------------------------------------------- #
# CSV (автоопределение кодировки и разделителя)
# --------------------------------------------------------------------------- #
def parse_csv(content: bytes) -> ParseResult:
    from charset_normalizer import from_bytes

    result = ParseResult()
    match = from_bytes(content).best()
    if match is None:
        text = content.decode("utf-8", errors="replace")
        result.warnings.append("Не удалось определить кодировку CSV — прочитано как UTF-8.")
    else:
        text = str(match)
        if match.encoding and match.encoding.lower() not in ("utf_8", "utf-8", "ascii"):
            result.warnings.append(f"Кодировка CSV определена как {match.encoding} — подтвердите.")

    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
        result.warnings.append(f"Разделитель CSV определён эвристикой как «{delimiter}» — подтвердите.")

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = _normalize_grid([list(r) for r in reader])
    if rows:
        result.tables.append(ParsedTable(sheet_or_page=None, table_index=0, rows=rows))
    else:
        result.warnings.append("CSV не содержит данных.")
    return result


# --------------------------------------------------------------------------- #
# Word .docx (таблицы; текст вне таблиц игнорируется в v1)
# --------------------------------------------------------------------------- #
def parse_docx(content: bytes) -> ParseResult:
    from docx import Document

    result = ParseResult()
    doc = Document(io.BytesIO(content))
    for idx, table in enumerate(doc.tables):
        grid = [[cell.text for cell in row.cells] for row in table.rows]
        rows = _normalize_grid(grid)
        if rows:
            result.tables.append(
                ParsedTable(sheet_or_page=f"Таблица {idx + 1}", table_index=idx, rows=rows)
            )
    if not result.tables:
        result.warnings.append("В документе Word не найдено таблиц (текст вне таблиц в v1 не извлекается).")
    return result


# --------------------------------------------------------------------------- #
# PDF (текстовый слой; OCR вне MVP)
# --------------------------------------------------------------------------- #
def parse_pdf(content: bytes) -> ParseResult:
    import pdfplumber

    result = ParseResult()
    has_text = False
    table_index = 0
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            if (page.extract_text() or "").strip():
                has_text = True
            for tbl in page.extract_tables():
                rows = _normalize_grid([list(r) for r in tbl])
                if rows:
                    result.tables.append(
                        ParsedTable(sheet_or_page=f"Стр. {page_no}", table_index=table_index, rows=rows)
                    )
                    table_index += 1
    if not has_text:
        result.warnings.append(
            "PDF без текстового слоя (вероятно, скан). Распознавание невозможно — OCR вне MVP."
        )
    elif not result.tables:
        result.warnings.append("В PDF есть текст, но таблицы не распознаны.")
    return result


# --------------------------------------------------------------------------- #
# Диспетчер по расширению
# --------------------------------------------------------------------------- #
_PARSERS = {
    "xlsx": parse_xlsx,
    "xls": parse_xls,
    "csv": parse_csv,
    "docx": parse_docx,
    "pdf": parse_pdf,
}


def parse(content: bytes, ext: str) -> ParseResult:
    ext = ext.lower().lstrip(".")
    parser = _PARSERS.get(ext)
    if parser is None:
        raise UnsupportedFormat(f"Формат .{ext} не поддерживается")
    return parser(content)
