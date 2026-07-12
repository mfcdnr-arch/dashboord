"""Маппинг распознанных столбцов на канонические поля и выпуск датасета.

Поток (док-06): пользователь выбирает табличную область, назначает столбец-метку
строки и сопоставляет остальные столбцы с каноническими полями объекта
(локальный справочник). Подтверждение → dataset_release + материализация значений.

При дубле (тот же объект/код/период) — конфликт: пользователь решает,
заместить прежний выпуск (supersede) или отменить (решение проекта).
"""
from __future__ import annotations

import json
from typing import List, Optional

from . import analyze


class ReleaseConflict(Exception):
    """Выпуск за этот период уже существует; нужен явный supersede."""

    def __init__(self, existing: dict):
        self.existing = existing
        super().__init__("Выпуск за этот период уже существует")


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
    by_slug = {analyze.slug(e["name"]): e["code"] for e in existing}

    # столбец-метка — первый текстовый (иначе первый столбец)
    label_idx = next((c["column_index"] for c in columns if c["inferred_type"] == "text"), None)
    if label_idx is None and columns:
        label_idx = columns[0]["column_index"]

    suggestions = []
    for c in columns:
        header = c["source_header"] or f"Столбец {c['column_index'] + 1}"
        code = c["canonical_field_code"] or by_slug.get(analyze.slug(header)) or analyze.slug(header)
        suggestions.append({
            "column_index": c["column_index"],
            "source_header": header,
            "field_code": code,
            "field_name": header,
            "data_type": c["inferred_type"],
            "is_row_label": c["column_index"] == label_idx,
            "confidence": float(c["confidence_score"]) if c["confidence_score"] is not None else None,
        })
    return {"row_label_column": label_idx, "columns": suggestions}


def _cast(value: str, data_type: str) -> dict:
    """Строковое значение ячейки → типизированные поля dataset_values."""
    out = {"value_text": value if value != "" else None, "value_number": None, "value_date": None}
    if data_type == "number":
        out["value_number"] = analyze.parse_number(value)
    elif data_type == "date":
        out["value_date"] = analyze.parse_date(value)
    return out


async def build_release(conn, *, job_id: str, table_id: str, code: str, name: str,
                        reporting_period_start, reporting_period_end,
                        fields: List[dict], supersede: bool, user: dict) -> dict:
    """Создаёт dataset_release, поля и материализует значения. Транзакция — снаружи."""
    ctx = await resolve_context(conn, job_id)
    if ctx is None:
        raise ValueError("Задание извлечения не найдено")
    object_id = ctx["object_id"]
    org_id = ctx["organization_id"]

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

    # материализация значений из полной сетки (пропускаем строки-шапки)
    table = await conn.fetchrow(
        "select header_rows, data from extracted_tables where id=$1::uuid", table_id
    )
    grid = json.loads(table["data"]) if table["data"] else []
    header_rows = table["header_rows"] or 0
    field_type = {f["field_code"]: f["data_type"] for f in value_fields}

    n_values = 0
    for row_index, row in enumerate(grid[header_rows:]):
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
        "rows": len(grid) - header_rows,
        "superseded_release_id": superseded_id,
    }
