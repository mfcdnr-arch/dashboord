"""Маппинг распознанных столбцов на канонические поля и выпуск датасета.

Поток (док-06): пользователь выбирает табличную область, назначает столбец-метку
строки и сопоставляет остальные столбцы с каноническими полями объекта
(локальный справочник). Подтверждение → dataset_release + материализация значений.

При дубле (тот же объект/код/период) — конфликт: пользователь решает,
заместить прежний выпуск (supersede) или отменить (решение проекта).
"""
from __future__ import annotations

import json
from typing import Any, List, Optional, Sequence

from . import analyze, parsers


class ReleaseConflict(Exception):
    """Выпуск за этот период уже существует; нужен явный supersede."""

    def __init__(self, existing: dict):
        self.existing = existing
        super().__init__("Выпуск за этот период уже существует")


def _norm_name(name: str) -> str:
    """Ключ сопоставления показателя с уже заведённым полем объекта.

    Только регистр и пробелы: имя показателя — единственное, что устойчиво
    повторяется в одной и той же форме за разные периоды.
    """
    return " ".join((name or "").split()).lower()


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
        row_label = row[label_col] if label_col is not None and label_col < len(row) else None
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
                        cells: Optional[List[dict]] = None) -> dict:
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

    # конфликт по (организация, код, период) — только среди АКТИВНЫХ выпусков
    existing = await conn.fetchrow(
        "select id, name, status, created_at from dataset_releases "
        "where organization_id=$1 and code=$2 and reporting_period_start is not distinct from $3 "
        "and status <> 'superseded'",
        org_id, code, reporting_period_start,
    )
    if existing is not None and not supersede:
        raise ReleaseConflict({
            "id": str(existing["id"]), "name": existing["name"],
            "status": existing["status"], "created_at": existing["created_at"].isoformat(),
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
    release = await conn.fetchrow(
        "insert into dataset_releases(organization_id, object_id, code, name, status, "
        "source_document_version_id, reporting_period_start, reporting_period_end, "
        "validated_by, validated_at, created_by) "
        "values($1,$2,$3,$4,'validated',$5,$6,$7,$8,now(),$8) returning id",
        org_id, object_id, code, name, ctx["document_version_id"],
        reporting_period_start, reporting_period_end, user["id"],
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
        # Сетка разметки: область данных, ориентация, развёрнутые объединения.
        # Без области в значения уехал бы текст письма над таблицей.
        area = analysis_grid(grid, merges, rect, lay["orientation"])
        rows_used = data_rows(area, header_rows, lay["skip_rows"] or [])
        for row_index, row in enumerate(rows_used):
            row_label = row[label_col] if label_col is not None and label_col < len(row) else None
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
        n_rows = len(rows_used)

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
        "values_count": n_values,
        "rows": n_rows,
        "superseded_release_id": superseded_id,
        "validation": {"warnings": warnings, "ok": len(warnings) == 0},
    }
