"""Модуль «Ingestion» (HTTP): запуск извлечения и просмотр результата.

- POST /document-versions/{version_id}/extract — поставить задачу извлечения;
- GET  /document-versions/{version_id}/extraction — последнее задание + результат;
- GET  /extraction-jobs/{job_id} — задание, распознанные таблицы и столбцы.

Правку разметки (границы/шапки/типы/маппинг) и выпуск датасета — этап 3.2.
"""
from __future__ import annotations

import json
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ... import db
from ..auth.deps import get_current_user, require_roles
from . import mapping, queue, service

router = APIRouter(tags=["ingestion"])
manage = require_roles("admin", "moderator")


async def _version_in_org(conn, version_id: str, org_id) -> bool:
    return bool(
        await conn.fetchval(
            "select 1 from document_versions dv join documents d on d.id=dv.document_id "
            "where dv.id=$1::uuid and d.organization_id=$2",
            version_id, org_id,
        )
    )


async def _job_in_org(conn, job_id: str, org_id) -> bool:
    return bool(
        await conn.fetchval(
            "select 1 from extraction_jobs ej "
            "join document_versions dv on dv.id=ej.document_version_id "
            "join documents d on d.id=dv.document_id "
            "where ej.id=$1::uuid and d.organization_id=$2",
            job_id, org_id,
        )
    )


async def _object_in_org(conn, object_id: str, org_id) -> bool:
    return bool(
        await conn.fetchval(
            "select 1 from objects where id=$1::uuid and organization_id=$2",
            object_id, org_id,
        )
    )


@router.post("/document-versions/{version_id}/extract", status_code=status.HTTP_202_ACCEPTED)
async def start_extraction(version_id: str, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        if not await _version_in_org(conn, version_id, user["organization_id"]):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Версия документа не найдена")
        job_id = await service.enqueue_or_run(conn, version_id)
    await queue.enqueue_extraction(job_id)
    return {"job_id": job_id, "status": "queued"}


async def _job_payload(conn, job_id: str) -> dict:
    job = await conn.fetchrow(
        "select id, document_version_id, status, engine, started_at, finished_at, "
        "error_message, confidence_score, warnings, created_at "
        "from extraction_jobs where id=$1::uuid",
        job_id,
    )
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Задание извлечения не найдено")
    tables = await conn.fetch(
        "select id, sheet_or_page, table_index, row_count, column_count, header_rows, raw_preview "
        "from extracted_tables where extraction_job_id=$1::uuid order by table_index",
        job_id,
    )
    out_tables = []
    for t in tables:
        cols = await conn.fetch(
            "select column_index, source_header, inferred_type, confidence_score, canonical_field_code "
            "from extracted_columns where extracted_table_id=$1 order by column_index",
            t["id"],
        )
        out_tables.append({
            "id": str(t["id"]),
            "sheet_or_page": t["sheet_or_page"],
            "table_index": t["table_index"],
            "row_count": t["row_count"],
            "column_count": t["column_count"],
            "header_rows": t["header_rows"],
            "preview": json.loads(t["raw_preview"]) if t["raw_preview"] else [],
            "columns": [dict(c) for c in cols],
        })
    return {
        "job_id": str(job["id"]),
        "document_version_id": str(job["document_version_id"]),
        "status": job["status"],
        "engine": job["engine"],
        "confidence_score": float(job["confidence_score"]) if job["confidence_score"] is not None else None,
        "warnings": json.loads(job["warnings"]) if job["warnings"] else [],
        "error_message": job["error_message"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
        "tables": out_tables,
    }


@router.get("/extraction-jobs/{job_id}")
async def get_job(job_id: str, user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        owns = await conn.fetchval(
            "select 1 from extraction_jobs ej "
            "join document_versions dv on dv.id=ej.document_version_id "
            "join documents d on d.id=dv.document_id "
            "where ej.id=$1::uuid and d.organization_id=$2",
            job_id, user["organization_id"],
        )
        if not owns:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Задание извлечения не найдено")
        return await _job_payload(conn, job_id)


@router.get("/document-versions/{version_id}/extraction")
async def get_latest_for_version(version_id: str, user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        if not await _version_in_org(conn, version_id, user["organization_id"]):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Версия документа не найдена")
        job_id = await conn.fetchval(
            "select id from extraction_jobs where document_version_id=$1::uuid "
            "order by created_at desc limit 1",
            version_id,
        )
        if job_id is None:
            return {"status": "none", "tables": []}
        return await _job_payload(conn, str(job_id))


# --------------------------------------------------------------------------- #
# Маппинг и выпуск датасета (этап 3.2)
# --------------------------------------------------------------------------- #
class FieldMap(BaseModel):
    column_index: int
    field_code: str = Field(min_length=1)
    field_name: str = Field(min_length=1)
    data_type: str = "text"  # number | date | text
    unit: Optional[str] = None
    is_row_label: bool = False


class ReleaseIn(BaseModel):
    table_id: str
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    reporting_period_start: Optional[date] = None
    reporting_period_end: Optional[date] = None
    fields: List[FieldMap]
    supersede: bool = False


class CanonicalFieldIn(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    data_type: str = "text"
    unit: Optional[str] = None
    is_row_label: bool = False
    description: Optional[str] = None


@router.get("/extraction-jobs/{job_id}/tables/{table_id}/mapping-suggestion")
async def mapping_suggestion(job_id: str, table_id: str, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        ctx = await mapping.resolve_context(conn, job_id)
        if ctx is None or ctx["organization_id"] != user["organization_id"]:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Задание извлечения не найдено")
        owns_table = await conn.fetchval(
            "select 1 from extracted_tables where id=$1::uuid and extraction_job_id=$2::uuid",
            table_id, job_id,
        )
        if not owns_table:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Таблица не найдена в задании")
        return await mapping.suggest_mapping(conn, table_id, ctx["object_id"])


@router.post("/extraction-jobs/{job_id}/release", status_code=status.HTTP_201_CREATED)
async def create_release(job_id: str, body: ReleaseIn, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        if not await _job_in_org(conn, job_id, user["organization_id"]):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Задание извлечения не найдено")
        try:
            async with conn.transaction():
                return await mapping.build_release(
                    conn, job_id=job_id, table_id=body.table_id, code=body.code,
                    name=body.name, reporting_period_start=body.reporting_period_start,
                    reporting_period_end=body.reporting_period_end,
                    fields=[f.model_dump() for f in body.fields],
                    supersede=body.supersede, user=user,
                )
        except mapping.ReleaseConflict as conflict:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"message": "Выпуск за этот период уже существует",
                        "existing": conflict.existing},
            )
        except ValueError as err:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(err))


@router.get("/objects/{object_id}/canonical-fields")
async def list_canonical_fields(object_id: str, user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        if not await _object_in_org(conn, object_id, user["organization_id"]):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден")
        rows = await conn.fetch(
            "select code, name, data_type, unit, is_row_label, description "
            "from canonical_fields where object_id=$1::uuid order by name",
            object_id,
        )
    return [dict(r) for r in rows]


@router.post("/objects/{object_id}/canonical-fields", status_code=status.HTTP_201_CREATED)
async def create_canonical_field(object_id: str, body: CanonicalFieldIn, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        if not await _object_in_org(conn, object_id, user["organization_id"]):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден")
        exists = await conn.fetchval(
            "select 1 from canonical_fields where object_id=$1::uuid and code=$2",
            object_id, body.code,
        )
        if exists:
            raise HTTPException(status.HTTP_409_CONFLICT, "Поле с таким кодом уже есть")
        row = await conn.fetchrow(
            "insert into canonical_fields(object_id, code, name, data_type, unit, is_row_label, description, created_by) "
            "values($1::uuid,$2,$3,$4,$5,$6,$7,$8) returning code, name, data_type, unit, is_row_label, description",
            object_id, body.code, body.name, body.data_type, body.unit,
            body.is_row_label, body.description, user["id"],
        )
    return dict(row)


@router.get("/objects/{object_id}/dataset-releases")
async def list_releases(object_id: str, user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        if not await _object_in_org(conn, object_id, user["organization_id"]):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден")
        rows = await conn.fetch(
            "select id, code, name, status, reporting_period_start, reporting_period_end, "
            "validated_at, created_at, superseded_by_release_id, "
            "(select count(*) from dataset_values dv where dv.dataset_release_id=r.id) as values_count "
            "from dataset_releases r where object_id=$1::uuid order by reporting_period_start desc nulls last, created_at desc",
            object_id,
        )
    return [dict(r) for r in rows]


@router.get("/dataset-releases/{release_id}")
async def get_release(release_id: str, limit: int = 200, user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        rel = await conn.fetchrow(
            "select id, code, name, status, object_id, reporting_period_start, reporting_period_end, "
            "validated_at, created_at, superseded_by_release_id "
            "from dataset_releases where id=$1::uuid and organization_id=$2",
            release_id, user["organization_id"],
        )
        if rel is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Выпуск датасета не найден")
        fields = await conn.fetch(
            "select canonical_field_code, extracted_column_id from dataset_release_fields "
            "where dataset_release_id=$1::uuid",
            release_id,
        )
        values = await conn.fetch(
            "select row_index, row_label, canonical_field_code, value_text, value_number, value_date "
            "from dataset_values where dataset_release_id=$1::uuid "
            "order by row_index limit $2",
            release_id, limit,
        )
    return {
        "release": dict(rel),
        "fields": [dict(f) for f in fields],
        "values": [dict(v) for v in values],
    }
