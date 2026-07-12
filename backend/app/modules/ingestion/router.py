"""Модуль «Ingestion» (HTTP): запуск извлечения и просмотр результата.

- POST /document-versions/{version_id}/extract — поставить задачу извлечения;
- GET  /document-versions/{version_id}/extraction — последнее задание + результат;
- GET  /extraction-jobs/{job_id} — задание, распознанные таблицы и столбцы.

Правку разметки (границы/шапки/типы/маппинг) и выпуск датасета — этап 3.2.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status

from ... import db
from ..auth.deps import get_current_user, require_roles
from . import queue, service

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
