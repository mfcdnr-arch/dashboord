"""Маппинг распознанных столбцов на канонические поля и выпуск датасета.

Поток (док-06): пользователь выбирает табличную область, назначает столбец-метку
строки и сопоставляет остальные столбцы с каноническими полями объекта
(локальный справочник). Подтверждение → dataset_release + материализация значений.

При дубле (тот же объект/код/период) — конфликт: пользователь решает,
заместить прежний выпуск (supersede) или отменить (решение проекта).
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, List, Optional, Sequence

from . import analyze, parsers


class ReleaseConflict(Exception):
    """Выпуск за этот период уже существует; нужен явный supersede."""

    def __init__(self, existing: dict):
        self.existing = existing
        super().__init__("Выпуск за этот период уже существует")


async def assert_code_free(conn, org_id, code: str, object_id) -> None:
    """Код датасета не должен быть занят ДРУГИМ объектом.

    Данные ищутся по паре «организация + код», объект в поиске не участвует
    (см. metrics/resolver._active_release), и ограничение уникальности в БД
    устроено так же — `(organization_id, code, reporting_period_start)`.
    Поэтому два объекта с одним кодом молча сливаются в один: выпуск за уже
    занятый период заместил бы ЧУЖОЙ, а виджеты первого объекта начали бы
    показывать данные второго. Отказ здесь дешевле разбора перепутанных
    данных потом.
    """
    foreign = await conn.fetchrow(
        "select o.name from dataset_releases r join objects o on o.id = r.object_id "
        "where r.organization_id=$1 and r.code=$2 and r.object_id is distinct from $3 "
        "limit 1", org_id, code, object_id)
    if foreign is not None:
        raise ValueError(
            f"Код «{code}» уже занят объектом «{foreign['name']}». Возьмите другой — "
            "иначе данные двух объектов смешаются: система ищет выпуски по коду, "
            "не различая объекты."
        )


_EMBEDDED_DATE_RE = re.compile(r"\d{1,2}\.\d{1,2}\.\d{2,4}")


def _norm_name(name: str) -> str:
    """Ключ сопоставления показателя с уже заведённым полем объекта — и ключ
    отпечатка структуры формы (`structure_fingerprint`).

    Регистр и пробелы — ожидаемо. А ДАТЫ ВНУТРИ ЗАГОЛОВКА — реальная находка,
    не гипотеза: у заказчика («ДНР_статистика») графа называется «Количество
    принятых заявлений с 01.01.2026 по 19.08.2026», и через неделю то же самое
    поле называется «…по 26.08.2026» — при точном сравнении строк это ДВЕ
    РАЗНЫЕ графы. Без вырезания даты показатель «переезжал» бы на новый код
    каждую неделю (тот же класс бага, что и «код уплывает» из-за обрезки
    заголовка, зафиксированный в истории проекта), а отпечаток структуры формы
    ни разу не совпал бы с прошлым выпуском — «Загрузка» просила бы ручную
    разметку КАЖДУЮ неделю вместо одного раза, что делает автораспознавание
    бесполезным именно там, где оно нужнее всего (форма с ролящейся датой).
    Пустая строка на месте даты — это нормально: то, что вокруг нее, всё равно
    достаточно уникально в пределах формы (проверено на реальном файле).
    """
    text = _EMBEDDED_DATE_RE.sub("", name or "")
    return " ".join(text.split()).lower()


async def resolve_context(conn, job_id: str) -> Optional[dict]:
    """object_id, organization_id и source_document_version_id по заданию извлечения."""
    return await conn.fetchrow(
        "select ej.document_version_id, d.organization_id, f.object_id "
        "from extraction_jobs ej "
        "join document_versions dv on dv.id = ej.document_version_id "
        "join documents d on d.id = dv.document_id "
        "join folders f on f.id = d.folder_id "
        "where ej.id = $1::uuid",
        job_id,
    )


async def _table_columns(conn, table_id: str) -> List[dict]:
    rows = await conn.fetch(
        "select id, column_index, source_header, inferred_type, confidence_score, canonical_field_code "
        "from extracted_columns where extracted_table_id=$1::uuid order by column_index",
        table_id,
    )
    return [dict(r) for r in rows]


async def suggest_mapping(conn, table_id: str, object_id) -> dict:
    """Авто-предложение маппинга: код/имя/тип поля + столбец-метка строки."""
    columns = await _table_columns(conn, table_id)
    existing = await conn.fetch(
        "select code, name, data_type from canonical_fields where object_id=$1", object_id
    )
    by_name: dict[str, str] = {}
    for e in existing:
        by_name.setdefault(_norm_name(e["name"]), e["code"])

    # столбец-метка — первый текстовый, кроме счётчика «№ п/п» (иначе первый)
    text_cols = [c for c in columns if c["inferred_type"] == "text"]
    label_idx = next(
        (c["column_index"] for c in text_cols
         if not analyze.is_counter_column(c["source_header"] or "")),
        None,
    )
    if label_idx is None:
        label_idx = text_cols[0]["column_index"] if text_cols else (
            columns[0]["column_index"] if columns else None)

    headers = [c["source_header"] or f"Столбец {c['column_index'] + 1}" for c in columns]
    # Коды обязаны быть различными: у формы с баннером во всю ширину все столбцы
    # получали один заголовок → один slug → нарушение unique на выпуске.
    names = analyze.short_names(headers)
    codes = analyze.dedupe_codes([
        c["canonical_field_code"] or by_name.get(_norm_name(n)) or analyze.slug(n)
        for c, n in zip(columns, names, strict=True)
    ])
    suggestions = []
    for c, header, code, short in zip(columns, headers, codes, names, strict=True):
        suggestions.append({
            "column_index": c["column_index"],
            "source_header": header,
            "field_code": code,
            "field_name": short,
            "data_type": c["inferred_type"],
            "is_row_label": c["column_index"] == label_idx,
            "confidence": float(c["confidence_score"]) if c["confidence_score"] is not None else None,
        })
    return {"row_label_column": label_idx, "columns": suggestions}


# --------------------------------------------------------------------------- #
# Разметка: область данных, ориентация, исключённые строки
# --------------------------------------------------------------------------- #
DEFAULT_LAYOUT: dict[str, Any] = {
    "data_rect": None, "header_rows": None, "orientation": "columns", "skip_rows": [],
}


def analysis_grid(
    grid: List[List[str]], merges, rect, orientation: str
) -> List[List[str]]:
    """Сетка, по которой считаются заголовки и значения.

    Объединения развёрнуты (название строки, объединённое на несколько строк,
    относится к каждой). Строки ограничены областью данных — иначе в значения
    уехал бы текст письма над таблицей.

    Столбцы при ориентации «показатели в столбцах» НЕ обрезаются: тогда индекс
    столбца в разметке совпадает с номером столбца в файле, и в системе живёт
    одна система координат вместо двух. При ориентации «показатели в строках»
    область транспонируется целиком, и индекс столбца означает позицию в
    транспонированной сетке (то есть исходную СТРОКУ).
    """
    filled = parsers.fill_merges(grid, merges)
    if not rect:
        return filled
    r1, c1, r2, c2 = rect
    rows = filled[r1 : r2 + 1]
    if orientation != "rows":
        return rows
    area = [row[c1 : c2 + 1] for row in rows]
    # strict=False сознательно: сетка выровнена по ширине ещё в парсере, но
    # падать на кривом файле при транспонировании мы не хотим — лучше короткий
    # столбец, чем ошибка вместо разметки.
    return [list(col) for col in zip(*area, strict=False)] if area else []


def data_row_items(
    area: List[List[str]], header_rows: int, skip_rows: Sequence[int] = ()
) -> List[tuple]:
    """(индекс в сетке разметки, строка) для строк данных без исключённых."""
    skip = set(skip_rows)
    return [(i, row) for i, row in enumerate(area[header_rows:], start=header_rows) if i not in skip]


def data_rows(area: List[List[str]], header_rows: int, skip_rows: Sequence[int] = ()) -> List[List[str]]:
    """Строки данных: ниже шапки, без исключённых пользователем."""
    return [row for _i, row in data_row_items(area, header_rows, skip_rows)]


def _suspect_rows(row_info, has_numeric_cols: bool) -> list:
    """Строки, которые почти наверняка не нужны в датасете.

    Без числовых столбцов подсказывать нечего — вернём пусто.

    Правило «числа без подписи» применяется, только если колонка названий
    реально заполнена хоть у одной строки: в формах, где подписей нет вовсе
    (данные в один ряд), иначе пришлось бы пометить подозрительными ВСЕ строки
    и предложить «исключить всё» — это сбивало бы с толку сильнее, чем молчание.
    """
    if not has_numeric_cols:
        return []
    labels_used = any(r["has_label"] for r in row_info)
    out = []
    for r in row_info:
        if not r["has_number"]:
            out.append(r["index"])            # подвал / пустая заготовка
        elif labels_used and not r["has_label"]:
            out.append(r["index"])            # числа есть, а подписи нет
    return out


async def layout_preview(
    conn, table_id: str, object_id, *, data_rect=None, header_rows=None,
    orientation: str = "columns", skip_rows: Sequence[int] = (), sample: int = 60,
) -> dict:
    """Пересчёт разметки под текущий выбор пользователя — без записи в БД.

    Конструктор разметки дёргает этот метод при каждом изменении области,
    числа строк шапки или ориентации. Считает ТОТ ЖЕ код, что и выпуск
    (`analyze` + `analysis_grid`), поэтому предпросмотр не может разойтись с
    тем, что реально уедет в датасет.
    """
    table = await conn.fetchrow(
        "select header_rows, data, merges, data_rect from extracted_tables where id=$1::uuid",
        table_id,
    )
    if table is None:
        raise ValueError("Таблица не найдена")
    grid = json.loads(table["data"]) if table["data"] else []
    merges = [tuple(m) for m in (json.loads(table["merges"]) if table["merges"] else [])]
    rect = list(data_rect) if data_rect else (
        json.loads(table["data_rect"]) if table["data_rect"] else [0, 0, len(grid) - 1, 0]
    )
    if not data_rect and not table["data_rect"] and grid:
        rect = [0, 0, len(grid) - 1, max(len(r) for r in grid) - 1]

    area = analysis_grid(grid, merges, rect, orientation)
    hdr = table["header_rows"] if header_rows is None else header_rows
    hdr = max(0, min(int(hdr or 0), len(area)))

    items = data_row_items(area, hdr, skip_rows)
    # Тип столбца определяем ТОЛЬКО по строкам, которые реально уедут в датасет.
    # В бланке под таблицей стоит подпись, и ФИО «Д.В.Регеда» попадает в столбец
    # значений: если считать тип по всем строкам, столбец становится текстовым,
    # число не пишется в value_number, и показатель на дашборде не считается.
    columns = analyze.analyze_columns(area[:hdr] + [row for _i, row in items], hdr)

    # Порядок важен: за именем закрепляется код, выданный ему ПЕРВЫМ. Если в
    # справочнике накопились варианты одного имени (например, после неудачного
    # выпуска), показатель не должен «переезжать» на новый код — иначе прошлые
    # периоды на дашборде отвалятся.
    existing = await conn.fetch(
        "select code, name from canonical_fields where object_id=$1 order by created_at, code",
        object_id,
    )
    # Сопоставляем с уже заведёнными полями по ПОЛНОМУ имени, а не по коду.
    # Код обрезан до 60 символов, и у граф «Количество обращений … нарастающим
    # итогом / за неделю» первые 60 символов совпадают: сопоставление по коду
    # промахивалось, второй выпуск той же формы получал НОВЫЕ коды (…_3_2), и
    # динамика по периодам разваливалась — соседние даты становились разными
    # показателями.
    by_name: dict[str, str] = {}
    for e in existing:
        by_name.setdefault(_norm_name(e["name"]), e["code"])
    headers = [c.source_header for c in columns]
    # Имя показателя — без общего для всех столбцов «шапочного» префикса;
    # полный путь остаётся в source_header и виден в колонке «Столбец в файле».
    names = analyze.short_names(headers)
    codes = analyze.dedupe_codes([by_name.get(_norm_name(n)) or analyze.slug(n) for n in names])

    # Столбец названий строк: первый текстовый, но НЕ счётчик «№ п/п» —
    # иначе подписями на дашборде становятся номера по порядку.
    text_cols = [c for c in columns if c.inferred_type == "text"]
    label_idx = next(
        (c.column_index for c in text_cols if not analyze.is_counter_column(c.source_header)),
        None,
    )
    if label_idx is None:
        label_idx = text_cols[0].column_index if text_cols else (columns[0].column_index if columns else None)

    rows = [row for _i, row in items]

    # Служебные строки. Все виды на дашборде дают пустую категорию либо тихо
    # искажают итоги:
    #   • подвал документа — ФИО согласующих, «Исполнитель: …», примечания:
    #     чисел в числовых столбцах нет вовсе;
    #   • заготовки формы — в бланке заранее пронумерованы строки под все
    #     субъекты, и незаполненные несут только порядковый номер. Правило «нет
    #     чисел» их НЕ ловит: номер по порядку сам числовой, поэтому смотрим
    #     ещё и на то, заполнено ли хоть что-то правее первого столбца области.
    #   • ЧИСЛА БЕЗ ПОДПИСИ — строка заполнена, но название субъекта/строки
    #     пустое. Самый опасный вид: показатель молча складывается по двум
    #     строкам, и число на дашборде вырастает вдвое без видимой причины
    #     (реальный случай в форме заказчика за 05.08.2026: строка «2» без
    #     названия субъекта добавляла 2 438 525 к отправленным уведомлениям).
    # Это подсказка, а не автоудаление: снимает их пользователь одной кнопкой.
    numeric_cols = [c.column_index for c in columns if c.inferred_type == "number"]
    first_col = columns[0].column_index if columns else 0
    row_info = []
    for i, row in items:
        label = row[label_idx] if label_idx is not None and label_idx < len(row) else ""
        has_number = any(
            analyze.parse_number(row[c]) is not None for c in numeric_cols if c < len(row)
        )
        filled_beyond_first = any(
            str(row[c.column_index]).strip()
            for c in columns
            if c.column_index != first_col and c.column_index < len(row)
        )
        row_info.append({
            "index": i, "label": label,
            "has_number": has_number and filled_beyond_first,
            "has_label": bool(str(label).strip()),
        })

    return {
        "data_rect": rect,
        "header_rows": hdr,
        "orientation": orientation,
        "row_label_column": label_idx,
        "row_count": len(rows),
        "rows": row_info,
        "suspect_rows": _suspect_rows(row_info, bool(numeric_cols)),
        "columns": [
            {
                "column_index": c.column_index,
                "source_header": c.source_header,
                "field_code": code,
                "field_name": short,
                "data_type": c.inferred_type,
                "is_row_label": c.column_index == label_idx,
                # Счётчик строк бланка показателем не является — конструктор
                # снимает такие столбцы сразу, чтобы «№ п/п» не уезжал на дашборд.
                "is_counter": analyze.is_counter_column(c.source_header),
                "confidence": c.confidence,
            }
            for c, code, short in zip(columns, codes, names, strict=True)
        ],
        "sample": rows[:sample],
    }


# --------------------------------------------------------------------------- #
# Шаблон разметки объекта: как размечали эту форму в прошлый раз
# --------------------------------------------------------------------------- #
def _jsonb(value, default):
    """jsonb из asyncpg приходит строкой; в тестах и словарём."""
    if value is None:
        return default
    return json.loads(value) if isinstance(value, str) else value


def structure_fingerprint(area: List[List[str]], header_rows: int, orientation: str = "columns") -> str:
    """Отпечаток СТРУКТУРЫ формы: состав и порядок заголовков + геометрия шапки.

    Нужен, чтобы отличить «та же форма за новую неделю» от «форма изменилась».
    Имя файла и контрольная сумма для этого не годятся: у заказчика недельные
    формы называются по-разному и различаются каждой цифрой, хотя бланк один.
    Значения в отпечаток НЕ входят — иначе он менялся бы каждую неделю.
    """
    cols = analyze.analyze_columns(area, max(0, int(header_rows or 0)))
    parts = [_norm_name(c.source_header) for c in cols]
    raw = f"{orientation}|{int(header_rows or 0)}|{len(parts)}|" + "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def structure_headers(area: List[List[str]], header_rows: int) -> List[str]:
    """Заголовки формы в порядке следования — для объяснения расхождений."""
    return [c.source_header for c in analyze.analyze_columns(area, max(0, int(header_rows or 0)))]


def describe_structure_change(old: Sequence[str], new: Sequence[str],
                              old_header_rows: int, new_header_rows: int) -> str:
    """Чем новый файл отличается от формы прошлого выпуска — словами.

    Отпечаток отвечает только «не совпало». Человеку нужно знать, ЧТО именно
    изменилось: одно дело добавили графу (разметить заново — минута), другое —
    прислали вообще другую форму.
    """
    old_norm = {_norm_name(h): h for h in old}
    new_norm = {_norm_name(h): h for h in new}
    added = [new_norm[k] for k in new_norm if k not in old_norm]
    gone = [old_norm[k] for k in old_norm if k not in new_norm]
    parts: List[str] = []

    # Ровно одна пропала и ровно одна появилась на том же месте — это
    # переименование, а не смена состава: так понятнее, чем два списка.
    if len(added) == 1 and len(gone) == 1:
        parts.append(f"графа «{_short(gone[0])}» переименована в «{_short(added[0])}»")
    else:
        if added:
            parts.append("добавились графы: " + ", ".join(f"«{_short(h)}»" for h in added[:5]))
        if gone:
            parts.append("пропали графы: " + ", ".join(f"«{_short(h)}»" for h in gone[:5]))

    if not added and not gone and list(old) != list(new):
        parts.append("изменился порядок граф")
    if int(old_header_rows or 0) != int(new_header_rows or 0):
        parts.append(f"этажей шапки было {old_header_rows}, стало {new_header_rows}")
    if len(old) != len(new) and not added and not gone:
        parts.append(f"столбцов было {len(old)}, стало {len(new)}")

    if not parts:
        return "структура формы отличается от прошлого выпуска"
    return "; ".join(parts)


def _short(header: str, limit: int = 60) -> str:
    """Хвост составного заголовка: различие у госформ как раз в конце."""
    h = " ".join((header or "").split())
    return h if len(h) <= limit else "…" + h[-(limit - 1):]


def _last_filled_row(grid: List[List[str]]) -> int:
    for i in range(len(grid) - 1, -1, -1):
        if any(str(v).strip() for v in grid[i]):
            return i
    return -1


def fit_rect(rect, grid: List[List[str]]) -> tuple[Optional[List[int]], bool]:
    """Область прошлой разметки, приложенная к новому файлу.

    Границы подрезаются под размер новой сетки, а если ниже области есть
    заполненные строки — область расширяется до последней из них: в этих формах
    список субъектов со временем растёт, и жёсткая нижняя граница молча
    отрезала бы новые строки. Расширение возвращается флагом — человеку
    сообщается, что границу стоит проверить (в подвал бланка тоже можно заехать,
    но такие строки ловит обычная подсказка о служебных строках).
    """
    if not rect or not grid:
        return (list(rect) if rect else None), False
    height = len(grid)
    width = max((len(r) for r in grid), default=0)
    r1, c1, r2, c2 = (int(v) for v in rect)
    r1 = max(0, min(r1, height - 1))
    c1 = max(0, min(c1, max(0, width - 1)))
    c2 = max(c1, min(c2, max(0, width - 1)))
    r2 = max(r1, min(r2, height - 1))
    last = _last_filled_row(grid)
    extended = last > r2
    if extended:
        r2 = last
    return [r1, c1, r2, c2], extended


async def save_layout_template(conn, *, object_id, fingerprint: str, mode: str, layout: dict,
                               fields: List[dict], cells: List[dict], row_count: int,
                               dataset_code: str, release_id, user_id,
                               headers: Optional[List[str]] = None) -> bool:
    """Запоминает разметку последнего выпуска. Один шаблон на объект.

    Возвращает True, если строка была ЗАВЕДЕНА этим вызовом (а не обновлена) —
    `xmax = 0` в системном столбце верно ровно для строки, вставленной в ЭТОЙ
    же команде, включая ветку `on conflict do update`. По этому признаку
    отличаем «форма распознаётся первый раз» от «пришёл очередной отчёт той же
    формы» — от него зависит, стоит ли предлагать вынести показатели на
    «Главную» (FR: спросить один раз, при первом выпуске новой формы).
    """
    row = await conn.fetchrow(
        "insert into object_layout_templates(object_id, fingerprint, mode, layout, fields, cells, "
        "row_count, dataset_code, source_release_id, updated_by, updated_at, headers) "
        "values($1,$2,$3,$4::jsonb,$5::jsonb,$6::jsonb,$7,$8,$9,$10,now(),$11::jsonb) "
        "on conflict (object_id) do update set fingerprint=excluded.fingerprint, mode=excluded.mode, "
        "layout=excluded.layout, fields=excluded.fields, cells=excluded.cells, "
        "row_count=excluded.row_count, dataset_code=excluded.dataset_code, "
        "source_release_id=excluded.source_release_id, updated_by=excluded.updated_by, "
        "updated_at=now(), headers=excluded.headers "
        "returning (xmax = 0) as inserted",
        object_id, fingerprint, mode,
        json.dumps(layout, ensure_ascii=False, default=str),
        json.dumps(fields, ensure_ascii=False, default=str),
        json.dumps(cells, ensure_ascii=False, default=str),
        int(row_count or 0), dataset_code, release_id, user_id,
        json.dumps(list(headers or []), ensure_ascii=False, default=str),
    )
    return bool(row["inserted"])


async def refresh_template_verdicts(conn, object_id, limit: int = 50) -> int:
    """Пересчитать «готов / требует внимания» у файлов объекта, ещё не выпущенных.

    Вердикт считается один раз — сразу после распознавания. Но шаблон объекта
    появляется ПОЗЖЕ, с первым выпуском: файлы, залитые до него, так и остались
    бы в состоянии «нужна разметка», хотя разметка для них уже есть. Человек
    увидел бы в папке стопку файлов, требующих его внимания, и не понял бы, что
    система уже умеет их разметить.

    Считаем только по невыпущенным файлам и с потолком: разбор сетки дорогой,
    а у выпущенных состояние всё равно «данные выпущены».
    """
    jobs = await conn.fetch(
        "select j.id from extraction_jobs j "
        "join document_versions dv on dv.id = j.document_version_id "
        "join documents d on d.id = dv.document_id "
        "join folders f on f.id = d.folder_id "
        "where f.object_id = $1 and j.status in ('succeeded','needs_review') "
        "  and not exists (select 1 from dataset_releases r "
        "                  where r.source_document_version_id = dv.id and r.status <> 'superseded') "
        "order by d.reporting_period_start desc nulls last limit $2",
        object_id, limit)
    updated = 0
    for j in jobs:
        tables = await conn.fetch(
            "select id from extracted_tables where extraction_job_id=$1 order by table_index", j["id"])
        tpl = await layout_template_for_tables(conn, object_id, [str(t["id"]) for t in tables])
        if tpl is None:
            continue
        await conn.execute(
            "update extraction_jobs set template_match=$2, template_note=$3 where id=$1",
            j["id"], tpl["match"], tpl["note"])
        updated += 1
    return updated


async def layout_template_for_tables(conn, object_id, table_ids: Sequence[str]) -> Optional[dict]:
    """Шаблон объекта, приложенный к таблицам текущего задания.

    Подставляем разметку ТОЛЬКО при совпадении отпечатка: не совпал — значит
    форма другая, и чужая разметка дала бы неверные цифры молча. В этом случае
    шаблон всё равно возвращается (с `match=structure_differs`), чтобы человек
    видел, что система его помнит, но применить не может.
    """
    tpl = await conn.fetchrow(
        "select t.fingerprint, t.mode, t.layout, t.fields, t.cells, t.row_count, t.dataset_code, t.headers, "
        "t.updated_at, r.name as release_name, r.reporting_period_start as release_period "
        "from object_layout_templates t "
        "left join dataset_releases r on r.id = t.source_release_id "
        "where t.object_id=$1", object_id)
    if tpl is None:
        return None

    lay = {**DEFAULT_LAYOUT, **_jsonb(tpl["layout"], {})}
    out: dict[str, Any] = {
        "mode": tpl["mode"],
        "fields": _jsonb(tpl["fields"], []),
        "cells": _jsonb(tpl["cells"], []),
        "dataset_code": tpl["dataset_code"],
        "updated_at": tpl["updated_at"],
        "source_release_name": tpl["release_name"],
        "source_release_period": (
            tpl["release_period"].isoformat() if tpl["release_period"] else None),
        "table_id": None,
        "match": "structure_differs",
        "layout": lay,
        "rows_differ": False,
        "diff": None,
        "note": "Форма отличается от прошлого выпуска — изменился состав или порядок граф. "
                "Разметьте её вручную: прошлая разметка дала бы неверные цифры.",
    }

    for tid in table_ids:
        row = await conn.fetchrow(
            "select data, merges, header_rows from extracted_tables where id=$1::uuid", tid)
        if row is None:
            continue
        grid = _jsonb(row["data"], [])
        merges = [tuple(m) for m in _jsonb(row["merges"], [])]
        rect, extended = fit_rect(lay["data_rect"], grid)
        hdr = int((lay["header_rows"] if lay["header_rows"] is not None else row["header_rows"]) or 0)
        area = analysis_grid(grid, merges, rect, lay["orientation"])
        if structure_fingerprint(area, hdr, lay["orientation"]) != tpl["fingerprint"]:
            # Не совпало — объясняем словами, ЧТО изменилось в бланке: по хешу
            # видно только «не то», а человеку решать, разметить заново или
            # искать, почему прислали другую форму.
            diff = describe_structure_change(
                _jsonb(tpl["headers"], []), structure_headers(area, hdr),
                int(lay["header_rows"] or 0), hdr)
            out["note"] = (f"Форма отличается от прошлого выпуска: {diff}. "
                           "Разметьте её вручную — прошлая разметка дала бы неверные цифры.")
            out["diff"] = diff
            continue

        rows_now = max(0, len(area) - hdr)
        same_rows = tpl["row_count"] in (None, 0) or rows_now == tpl["row_count"]
        note = "Разметка подставлена из прошлого выпуска — проверьте и подтвердите выпуск."
        if not same_rows or extended:
            note = (f"Разметка подставлена из прошлого выпуска, но строк в файле другое количество "
                    f"({rows_now} вместо {tpl['row_count']}). Область данных расширена до последней "
                    "заполненной строки, исключённые ранее строки не перенесены — проверьте область.")
        out.update({
            "table_id": str(tid),
            "match": "exact",
            "layout": {
                "data_rect": rect,
                "header_rows": hdr,
                "orientation": lay["orientation"],
                # Исключённые строки позиционные: при другом числе строк они
                # указали бы на ЧУЖИЕ строки и молча выбросили бы данные.
                "skip_rows": list(lay["skip_rows"] or []) if same_rows else [],
            },
            "rows_differ": (not same_rows) or extended,
            "note": note,
        })
        break

    return out


async def quality_warnings(conn, org_id, *, code: str, period, rows: List[List[str]],
                           fields: List[dict], label_col: Optional[int]) -> List[dict]:
    """Замечания по качеству готовящихся данных.

    Одна функция и для предпросмотра, и для выпуска — иначе «перед выпуском
    замечаний не было, а после выпуска появились» стало бы неизбежным.

    Прошлого выпуска может не быть (первый файл формы) — это НЕ повод молчать:
    арифметику внутри файла (сумма против итога, неделя против накопительного,
    факт против плана) проверять всё равно есть чем, и раньше именно на первом
    файле не срабатывало ничего.
    """
    from . import quality

    previous, prev_period = await quality.previous_release_values(conn, org_id, code, period)
    current = quality.values_from_rows(rows, fields, label_col)
    if not current:
        return []
    names = {f["field_code"]: f["field_name"] for f in fields}
    return quality.check_release(current, names, previous, prev_period)


def _cast(value: str, data_type: str) -> dict:
    """Строковое значение ячейки → типизированные поля dataset_values."""
    out: dict[str, Any] = {"value_text": value if value != "" else None, "value_number": None, "value_date": None}
    if data_type == "number":
        out["value_number"] = analyze.parse_number(value)
    elif data_type == "date":
        out["value_date"] = analyze.parse_date(value)
    return out


def _validate_grid(rows, value_fields, label_col, field_type) -> list:
    """Проверка бизнес-правил при загрузке (чистая, без БД): дубли строк, строки
    без названия, число не распозналось, отрицательные значения, пропуски.
    Возвращает список предупреждений [{code, count, message}] — НЕ блокирует релиз."""
    empty_rows = 0
    seen: dict = {}
    unparsed: list = []
    negative: list = []
    missing = 0
    for row in rows:
        row_label = analyze.clean_row_label(row[label_col] if label_col is not None and label_col < len(row) else None)
        if row_label is None or not str(row_label).strip():
            empty_rows += 1
        else:
            seen[row_label] = seen.get(row_label, 0) + 1
        for f in value_fields:
            fcode = f["field_code"]
            if field_type.get(fcode) != "number":
                continue
            ci = f["column_index"]
            raw = row[ci] if ci < len(row) else ""
            num = analyze.parse_number(raw)
            if num is None:
                if str(raw).strip():
                    unparsed.append(f"{row_label or '—'}·{fcode}: «{str(raw)[:20]}»")
                else:
                    missing += 1
            elif num < 0:
                negative.append(f"{row_label or '—'}·{fcode}: {num}")

    warnings = []
    dups = {k: c for k, c in seen.items() if c > 1}
    if dups:
        warnings.append({"code": "duplicate_rows", "count": len(dups),
                         "message": f"Повторяющиеся названия строк: {len(dups)} ({', '.join(map(str, list(dups)[:5]))})"})
    if empty_rows:
        warnings.append({"code": "empty_rows", "count": empty_rows,
                         "message": f"Строки без названия: {empty_rows}"})
    if unparsed:
        warnings.append({"code": "not_a_number", "count": len(unparsed),
                         "message": f"Число не распознано в {len(unparsed)} ячейках: {'; '.join(unparsed[:5])}"})
    if negative:
        warnings.append({"code": "negative", "count": len(negative),
                         "message": f"Отрицательные значения: {len(negative)} ({'; '.join(negative[:5])})"})
    if missing:
        warnings.append({"code": "missing_values", "count": missing,
                         "message": f"Пропущенные числовые значения: {missing}"})
    return warnings


async def build_release(conn, *, job_id: str, table_id: str, code: str, name: str,
                        reporting_period_start, reporting_period_end,
                        fields: List[dict], supersede: bool, user: dict,
                        layout: Optional[dict] = None,
                        cells: Optional[List[dict]] = None,
                        auto: bool = False) -> dict:
    """Создаёт dataset_release, поля и материализует значения. Транзакция — снаружи.

    `layout` — что именно пользователь выделил в конструкторе разметки:
    область данных, число строк шапки, ориентация, исключённые строки. Если не
    передан, берётся то, что предложила система при распознавании.

    `cells` — режим отдельных ячеек: список {row, col, field_code, field_name,
    data_type} в координатах ИСХОДНОЙ сетки. Нужен для форм «приложение к
    письму», где важны несколько конкретных цифр, а размечать таблицу целиком
    незачем. Даёт выпуск из одной строки.
    """
    ctx = await resolve_context(conn, job_id)
    if ctx is None:
        raise ValueError("Задание извлечения не найдено")
    object_id = ctx["object_id"]
    org_id = ctx["organization_id"]

    if cells:
        # Поля выводим из выбранных ячеек: справочник канонических полей и
        # dataset_release_fields ниже работают одинаково в обоих режимах.
        fields = [
            {
                "column_index": i, "field_code": c["field_code"], "field_name": c["field_name"],
                "data_type": c.get("data_type") or "text", "is_row_label": False,
            }
            for i, c in enumerate(cells)
        ]
    if not fields:
        raise ValueError("Не выбрано ни одного показателя")

    # Дубли кодов ловим здесь: иначе вставка в dataset_release_fields нарушит
    # unique (dataset_release_id, canonical_field_code) и пользователь увидит
    # сырую ошибку БД вместо объяснения, что два столбца названы одинаково.
    seen_codes: dict[str, str] = {}
    for f in fields:
        code_ = f["field_code"]
        if code_ in seen_codes:
            raise ValueError(
                f"Столбцы «{seen_codes[code_]}» и «{f['field_name']}» дают один код поля «{code_}». "
                "Переименуйте один из них или снимите лишний столбец."
            )
        seen_codes[code_] = f["field_name"]

    await assert_code_free(conn, org_id, code, object_id)

    # конфликт по (организация, код, период) — только среди АКТИВНЫХ выпусков
    existing = await conn.fetchrow(
        "select id, name, status, created_at, auto_released from dataset_releases "
        "where organization_id=$1 and code=$2 and reporting_period_start is not distinct from $3 "
        "and status <> 'superseded'",
        org_id, code, reporting_period_start,
    )
    if existing is not None and not supersede:
        # `auto` в отказе — чтобы человек понял, ПОЧЕМУ период занят, хотя он
        # ничего не выпускал: данные выпустил автомат по совпадению формы.
        raise ReleaseConflict({
            "id": str(existing["id"]), "name": existing["name"],
            "status": existing["status"], "created_at": existing["created_at"].isoformat(),
            "auto": bool(existing["auto_released"]),
        })

    # supersede: помечаем прежний выпуск ДО вставки нового (частичный unique-индекс
    # uq_dataset_releases_active игнорирует superseded → вставка не конфликтует)
    if existing is not None and supersede:
        await conn.execute(
            "update dataset_releases set status='superseded' where id=$1", existing["id"]
        )

    # справочник: upsert канонических полей объекта
    for f in fields:
        await conn.execute(
            "insert into canonical_fields(object_id, code, name, data_type, unit, is_row_label, created_by) "
            "values($1,$2,$3,$4,$5,$6,$7) "
            "on conflict (object_id, code) do update set "
            "name=excluded.name, data_type=excluded.data_type, unit=excluded.unit, "
            "is_row_label=excluded.is_row_label",
            object_id, f["field_code"], f["field_name"], f["data_type"],
            f.get("unit"), bool(f.get("is_row_label")), user["id"],
        )

    # выпуск (status=validated: данные подтверждены; публикация — в модерации)
    # `auto_released` отвечает на вопрос «кто нажал кнопку»: автором остаётся
    # живой человек (тот, кто загрузил файл), но выпуск, сделанный автоматом по
    # его загрузке, не должен выглядеть как его собственное решение.
    release = await conn.fetchrow(
        "insert into dataset_releases(organization_id, object_id, code, name, status, "
        "source_document_version_id, reporting_period_start, reporting_period_end, "
        "validated_by, validated_at, created_by, auto_released) "
        "values($1,$2,$3,$4,'validated',$5,$6,$7,$8,now(),$8,$9) returning id",
        org_id, object_id, code, name, ctx["document_version_id"],
        reporting_period_start, reporting_period_end, user["id"], bool(auto),
    )
    release_id = release["id"]

    # столбцы таблицы: column_index -> extracted_column_id
    columns = await _table_columns(conn, table_id)
    col_id_by_index = {c["column_index"]: c["id"] for c in columns}

    label_field = next((f for f in fields if f.get("is_row_label")), None)
    label_col = label_field["column_index"] if label_field else None
    value_fields = [f for f in fields if not f.get("is_row_label")]

    # dataset_release_fields + отметка маппинга на извлечённом столбце
    for f in fields:
        col_id = col_id_by_index.get(f["column_index"])
        await conn.execute(
            "insert into dataset_release_fields(dataset_release_id, canonical_field_code, extracted_column_id) "
            "values($1,$2,$3)",
            release_id, f["field_code"], col_id,
        )
        if col_id is not None:
            await conn.execute(
                "update extracted_columns set canonical_field_code=$2 where id=$1",
                col_id, f["field_code"],
            )

    # материализация значений из полной сетки
    table = await conn.fetchrow(
        "select header_rows, data, merges, data_rect from extracted_tables where id=$1::uuid",
        table_id,
    )
    grid = json.loads(table["data"]) if table["data"] else []
    merges = [tuple(m) for m in (json.loads(table["merges"]) if table["merges"] else [])]
    lay = {**DEFAULT_LAYOUT, **(layout or {})}
    rect = lay["data_rect"] or (json.loads(table["data_rect"]) if table["data_rect"] else None)
    header_rows = table["header_rows"] if lay["header_rows"] is None else lay["header_rows"]
    header_rows = int(header_rows or 0)
    field_type = {f["field_code"]: f["data_type"] for f in value_fields}

    # Сетка разметки нужна обоим режимам: по ней материализуются значения и по
    # ней же считается отпечаток структуры для шаблона объекта.
    area = analysis_grid(grid, merges, rect, lay["orientation"])

    n_values = 0
    if cells:
        # Режим отдельных ячеек: один «ряд» значений, подписанный названием
        # выпуска — на дашборде такие показатели ведут себя как обычные числа.
        filled = parsers.fill_merges(grid, merges)
        for f, cell in zip(fields, cells, strict=True):
            r, c = int(cell["row"]), int(cell["col"])
            raw = filled[r][c] if r < len(filled) and c < len(filled[r]) else ""
            casted = _cast(raw, f["data_type"])
            await conn.execute(
                "insert into dataset_values(dataset_release_id, row_index, row_label, "
                "canonical_field_code, value_text, value_number, value_date) "
                "values($1,0,$2,$3,$4,$5,$6)",
                release_id, name, f["field_code"],
                casted["value_text"], casted["value_number"], casted["value_date"],
            )
            n_values += 1
        warnings = []
        n_rows = 1
    else:
        # Область данных, ориентация, развёрнутые объединения: без области в
        # значения уехал бы текст письма над таблицей.
        rows_used = data_rows(area, header_rows, lay["skip_rows"] or [])
        for row_index, row in enumerate(rows_used):
            row_label = analyze.clean_row_label(row[label_col] if label_col is not None and label_col < len(row) else None)
            for f in value_fields:
                ci = f["column_index"]
                raw = row[ci] if ci < len(row) else ""
                casted = _cast(raw, field_type[f["field_code"]])
                await conn.execute(
                    "insert into dataset_values(dataset_release_id, row_index, row_label, "
                    "canonical_field_code, value_text, value_number, value_date) "
                    "values($1,$2,$3,$4,$5,$6,$7)",
                    release_id, row_index, row_label, f["field_code"],
                    casted["value_text"], casted["value_number"], casted["value_date"],
                )
                n_values += 1
        warnings = _validate_grid(rows_used, value_fields, label_col, field_type)
        # Сверка с прошлой неделей: перенесённые без обновления цифры — самая
        # дорогая ошибка в этих формах, и заметить её по одному файлу нельзя.
        warnings += await quality_warnings(
            conn, org_id, code=code, period=reporting_period_start,
            rows=rows_used, fields=fields, label_col=label_col)
        n_rows = len(rows_used)

    # Запоминаем разметку: следующий файл этой же формы придёт размеченным, и
    # человеку останется проверить и подтвердить, а не размечать заново.
    is_first_template = await save_layout_template(
        conn, object_id=object_id,
        fingerprint=structure_fingerprint(area, header_rows, lay["orientation"]),
        mode="cells" if cells else "table",
        layout={
            "data_rect": rect, "header_rows": header_rows,
            "orientation": lay["orientation"], "skip_rows": list(lay["skip_rows"] or []),
        },
        headers=structure_headers(area, header_rows),
        fields=fields, cells=cells or [],
        # Строк в области ДО исключений: с этим числом сравнивается новый файл,
        # чтобы понять, можно ли перенести позиционные «снятые строки». Число
        # выпущенных строк (n_rows) для этого не годится — оно уже за вычетом.
        row_count=max(0, len(area) - header_rows),
        dataset_code=code, release_id=release_id, user_id=user["id"],
    )
    # Файлы, залитые ДО появления шаблона, должны узнать, что разметка для них
    # теперь есть: иначе папка показывала бы «нужна разметка» на всей пачке.
    await refresh_template_verdicts(conn, object_id)

    # проставляем ссылку на замещающий выпуск (сам статус уже 'superseded')
    superseded_id = None
    if existing is not None and supersede:
        superseded_id = str(existing["id"])
        await conn.execute(
            "update dataset_releases set superseded_by_release_id=$2 where id=$1",
            existing["id"], release_id,
        )

    return {
        "release_id": str(release_id),
        "status": "validated",
        "auto": bool(auto),
        "values_count": n_values,
        "rows": n_rows,
        "superseded_release_id": superseded_id,
        # Форма распознана первый раз — самое время спросить, какие показатели
        # вынести на «Главную» ключевыми: до этого момента поля формы ещё не
        # существовали, а после первого раза повторный вопрос был бы навязчив.
        "new_form": is_first_template,
        "dataset_code": code,
        "numeric_fields": [{"field_code": f["field_code"], "field_name": f["field_name"]}
                           for f in value_fields if field_type.get(f["field_code"]) == "number"],
        "validation": {"warnings": warnings, "ok": len(warnings) == 0},
    }


async def match_any_template(conn, org_id, table_ids: Sequence[str]) -> List[dict]:
    """Формы организации, отпечаток которых совпал с этим файлом.

    Нужна общей зоне загрузки: человек кладёт файл, не выбирая папку, и систему
    просят узнать форму «в лицо». Сравнить хеши напрямую нельзя — отпечаток
    считается ПО РАЗМЕТКЕ (область данных, число этажей шапки, ориентация), а у
    каждого шаблона она своя; поэтому область файла выкраивается по разметке
    КАЖДОГО шаблона и только потом сравнивается.

    Возвращает все совпадения, а не первое: две формы с одинаковой структурой —
    повод спросить человека, а не выбрать за него молча.
    """
    tpls = await conn.fetch(
        "select t.object_id, t.fingerprint, t.layout, t.dataset_code, o.name as object_name, "
        "  t.source_release_id "
        "from object_layout_templates t join objects o on o.id = t.object_id "
        "where o.organization_id=$1", org_id)
    if not tpls:
        return []
    tables = []
    for tid in table_ids:
        row = await conn.fetchrow(
            "select data, merges, header_rows from extracted_tables where id=$1::uuid", tid)
        if row is not None:
            tables.append((tid, _jsonb(row["data"], []),
                           [tuple(m) for m in _jsonb(row["merges"], [])], row["header_rows"]))
    out: List[dict] = []
    for tpl in tpls:
        lay = {**DEFAULT_LAYOUT, **_jsonb(tpl["layout"], {})}
        for tid, grid, merges, hdr_rows in tables:
            rect, _extended = fit_rect(lay["data_rect"], grid)
            hdr = int((lay["header_rows"] if lay["header_rows"] is not None else hdr_rows) or 0)
            area = analysis_grid(grid, merges, rect, lay["orientation"])
            if structure_fingerprint(area, hdr, lay["orientation"]) == tpl["fingerprint"]:
                out.append({"object_id": tpl["object_id"], "object_name": tpl["object_name"],
                            "dataset_code": tpl["dataset_code"],
                            "source_release_id": tpl["source_release_id"], "table_id": str(tid)})
                break
    return out
