"""Анализ распознанной таблицы: строки-шапки и типы столбцов.

Чистые функции над нормализованной сеткой (см. parsers.ParsedTable.rows).
Результат — предложение системы, которое пользователь правит вручную (док-06).
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

# Прямоугольник (r1, c1, r2, c2) — границы включительно, нумерация с нуля.
Rect = Tuple[int, int, int, int]

# Порядок важен: сначала более специфичные форматы дат.
_DATE_FORMATS = (
    "%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y",
    "%Y.%m.%d", "%m/%d/%Y", "%d.%m.%y",
)
_NUM_CLEAN_RE = re.compile(r"[\s  ]")  # пробелы, неразрывные пробелы (разряды)


# Транслитерация кириллицы для машинного кода поля (slug).
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}
_SLUG_CLEAN_RE = re.compile(r"[^a-z0-9]+")


MAX_CODE_LEN = 60


def slug(text: str) -> str:
    """Заголовок → машинный код поля: транслит + нижний регистр + '_'.

    Длина ограничена: код многоэтажного заголовка разворачивался в 85 символов
    («kolichestvo_polzovateley_zapisavshihsya_na_poseschenie_mfc_…»), а его
    руками пишут в формулах метрик. Режем по границе слова, различие кодов
    после обрезки обеспечивает `dedupe_codes`.
    """
    text = text.lower()
    out = "".join(_TRANSLIT.get(ch, ch) for ch in text)
    out = _SLUG_CLEAN_RE.sub("_", out).strip("_")
    if len(out) > MAX_CODE_LEN:
        cut = out[:MAX_CODE_LEN]
        out = cut[: cut.rfind("_")] if "_" in cut[1:] else cut
    return out or "field"


@dataclass
class ColumnInfo:
    column_index: int
    source_header: str
    inferred_type: str  # 'number' | 'date' | 'text'
    confidence: float   # 0..1 — доля значений столбца, подходящих под тип


def parse_number(s: str) -> Optional[float]:
    """Строка → число (учёт разрядных пробелов, десятичной запятой, %). None если не число."""
    if not s:
        return None
    t = _NUM_CLEAN_RE.sub("", s).replace("%", "")
    # десятичная запятая → точка (если запятая одна и точек нет)
    if t.count(",") == 1 and t.count(".") == 0:
        t = t.replace(",", ".")
    else:
        t = t.replace(",", "")  # запятая как разрядный разделитель
    if t in ("", "-", "+", ".", "-.", "+."):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def parse_date(s: str) -> Optional[dt.date]:
    """Строка → дата по известным форматам. None если не дата."""
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _is_number(s: str) -> bool:
    return parse_number(s) is not None


def _is_date(s: str) -> bool:
    return parse_date(s) is not None


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


def detect_data_rect(rows: List[List[str]], merges: Sequence[Rect] = ()) -> Rect:
    """Где на листе начинается сама таблица: (r1, c1, r2, c2), включительно.

    Отчёты госсектора приходят как «приложение к письму»: сверху лежит баннер
    («ИНФОРМАЦИЯ», «Приложение к письму от __.2026 № __»), объединённый во всю
    ширину листа, и только потом таблица. Раньше эти строки считались шапкой
    таблицы, и их текст становился именем КАЖДОГО столбца.

    Признак баннера намеренно простой и объяснимый: верхняя строка, которая
    либо накрыта объединением ОТ КРАЯ ДО КРАЯ листа, либо содержит не больше
    одной непустой ячейки. Считаем от первой строки вниз и останавливаемся,
    как только пошла структура. Это ПРЕДПОЛОЖЕНИЕ — пользователь поправляет
    область одним движением мыши в конструкторе разметки.

    Требование «от края до края» существенно: этаж многоуровневой шапки тоже
    объединён на много столбцов («Показатели эффективности» над всеми колонками
    значений), но начинается он не с первого столбца — слева стоит столбец с
    названиями строк. Тест `test_banner_excluded_from_data_rect` держит границу.
    """
    if not rows:
        return (0, 0, -1, -1)
    height = len(rows)
    width = max(len(r) for r in rows)

    banner_rows: set[int] = set()
    for r1, c1, r2, c2 in merges:
        if c1 == 0 and c2 == width - 1:
            banner_rows.update(range(r1, r2 + 1))

    start = 0
    for r in range(height):
        filled = sum(1 for c in rows[r] if c.strip())
        if r in banner_rows or filled <= 1:
            start = r + 1
        else:
            break
    if start >= height:  # лист целиком «баннерный» — не режем, отдаём как есть
        start = 0
    return (start, 0, height - 1, width - 1)


def is_numbering_row(row: List[str]) -> bool:
    """Строка нумерации граф: «1 2 3 4 …» под шапкой.

    Обязательный элемент госформ. Раньше она уезжала в данные, потому что
    `guess_header_rows` останавливается на первой строке с числами — и первая
    строка датасета выглядела как «3, 4» вместо реальных значений.
    """
    values = [c.strip() for c in row if c.strip()]
    if len(values) < 3:
        return False
    numbers: List[int] = []
    for v in values:
        n = parse_number(v)
        if n is None or n != int(n):
            return False
        numbers.append(int(n))
    return numbers == list(range(1, len(numbers) + 1))


def guess_header_rows(rows: List[List[str]], rect: Optional[Rect] = None) -> int:
    """Сколько верхних строк ОБЛАСТИ ДАННЫХ — шапка.

    Эвристика прежняя (строки без чисел сверху), но считается уже внутри
    области данных и допускает до пяти «этажей»: в реальных формах шапка вида
    «Показатели → Количество пользователей → Факт → за отчётную неделю»
    занимает четыре уровня, а прежний предел в три уровня разрезал её посередине.
    """
    if not rows:
        return 0
    r1, _c1, r2, _c2 = rect or (0, 0, len(rows) - 1, max(len(r) for r in rows) - 1)
    area = rows[r1 : r2 + 1]
    if not area:
        return 0
    header = 0
    for row in area[: min(5, len(area))]:
        if any(_is_number(c) for c in row):
            break
        header += 1
    header = max(1, header) if len(area) > 1 else 0
    # Строка нумерации граф идёт сразу под шапкой и состоит из чисел, поэтому
    # цикл выше на ней и останавливается. Забираем её в шапку отдельно.
    if header < len(area) and is_numbering_row(area[header]):
        header += 1
    return header


def _compose_header(header_rows: List[List[str]], col: int) -> str:
    """Многоэтажная шапка → составное имя столбца (док-06)."""
    parts: List[str] = []
    for hr in header_rows:
        val = hr[col].strip() if col < len(hr) else ""
        if val and val not in parts:
            parts.append(val)
    return " · ".join(parts)


def analyze_columns(
    rows: List[List[str]], header_rows: int, rect: Optional[Rect] = None
) -> List[ColumnInfo]:
    """Метаданные столбцов: составной заголовок + тип по данным ниже шапки.

    `rows` ожидается с УЖЕ развёрнутыми объединениями (parsers.fill_merges):
    иначе заголовок, объединённый на несколько столбцов, достался бы только
    первому из них. Индексы столбцов — абсолютные координаты сетки, чтобы
    совпадать с тем, что видит пользователь в предпросмотре.
    """
    if not rows:
        return []
    r1, c1, r2, c2 = rect or (0, 0, len(rows) - 1, max(len(r) for r in rows) - 1)
    # Нумерация граф относится к шапке (в данные её пускать нельзя), но в имя
    # показателя добавлять нечего — иначе получим «… · 3».
    headers = [h for h in rows[r1 : r1 + header_rows] if not is_numbering_row(h)]
    data = rows[r1 + header_rows : r2 + 1]
    columns: List[ColumnInfo] = []
    for c in range(c1, c2 + 1):
        header = _compose_header(headers, c) if headers else ""
        if not header:
            header = f"Столбец {c + 1}"
        col_values = [row[c] if c < len(row) else "" for row in data]
        inferred, conf = infer_type(col_values)
        columns.append(
            ColumnInfo(column_index=c, source_header=header, inferred_type=inferred, confidence=conf)
        )
    return columns


HEADER_SEP = " · "


def short_names(headers: Sequence[str]) -> List[str]:
    """Имена показателей без общего «шапочного» префикса.

    Многоэтажная шапка даёт составные заголовки вида «Показатели эффективности
    внедрения сервиса · Количество пользователей · за отчётную неделю». В форме
    разметки все шесть таких имён выглядят одинаково — различие уезжает за
    правый край поля ввода, и пользователь не понимает, что выбирает.

    Отрезаем верхние уровни, ОДИНАКОВЫЕ у всех многоуровневых заголовков:
    общий заголовок таблицы не различает столбцы, а место занимает. Столбцы с
    одним уровнем (например «Субъект») не трогаем — у них резать нечего, и они
    не должны мешать поиску общего префикса.
    """
    parts = [h.split(HEADER_SEP) for h in headers]
    multi = [p for p in parts if len(p) > 1]
    common = 0
    if len(multi) > 1:
        shortest = min(len(p) for p in multi)
        while common < shortest - 1 and len({p[common] for p in multi}) == 1:
            common += 1
    return [
        HEADER_SEP.join(p[common:]) if len(p) > 1 and len(p) > common else HEADER_SEP.join(p)
        for p in parts
    ]


def dedupe_codes(codes: Sequence[str]) -> List[str]:
    """Делает коды полей различными, сохраняя порядок: повторы получают _2, _3 …

    Столбцы с одинаковым заголовком давали один и тот же slug, а на
    `dataset_release_fields` висит unique (dataset_release_id,
    canonical_field_code) — выпуск падал сырой ошибкой БД.
    """
    used: set[str] = set()
    out: List[str] = []
    for base in codes:
        code = base
        n = 2
        while code in used:
            code = f"{base}_{n}"
            n += 1
        used.add(code)
        out.append(code)
    return out
