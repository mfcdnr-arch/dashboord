"""Оркестрация задания извлечения: файл (MinIO) → парсер → запись в БД.

Выполняется в фоновом воркере (arq). Заполняет:
  extraction_jobs (статус/тайминги/уверенность/предупреждения),
  extracted_tables (шапка, счётчики, предпросмотр, полная сетка),
  extracted_columns (составной заголовок, тип, уверенность, канон. поле — позже).
"""
from __future__ import annotations

import asyncio
import json
from typing import List

from ... import db
from ..documents import storage
from . import analyze, parsers

PREVIEW_ROWS = 100  # усечение предпросмотра для UI (открытый вопрос док-06 — дефолт)


async def run_extraction(job_id: str) -> None:
    """Полный прогон одного задания извлечения (по id из extraction_jobs)."""
    pool = db.get_pool()
    async with pool.acquire() as conn:
        job = await conn.fetchrow(
            "select ej.id, ej.document_version_id, dv.storage_path, d.source_type, d.id as document_id "
            "from extraction_jobs ej "
            "join document_versions dv on dv.id = ej.document_version_id "
            "join documents d on d.id = dv.document_id "
            "where ej.id = $1::uuid",
            job_id,
        )
        if job is None:
            return
        await conn.execute(
            "update extraction_jobs set status='running', started_at=now(), error_message=null "
            "where id=$1::uuid",
            job_id,
        )
        await conn.execute(
            "update documents set status='parsing' where id=$1", job["document_id"]
        )

    try:
        content = await asyncio.to_thread(storage.get_object, job["storage_path"])
        result = await asyncio.to_thread(parsers.parse, content, job["source_type"])
    except Exception as exc:  # noqa: BLE001 — любая ошибка парсинга должна пометить job
        await _fail(job_id, job["document_id"], str(exc))
        return

    confidences: List[float] = []
    async with pool.acquire() as conn:
        async with conn.transaction():
            # очистка прежних результатов (повторный прогон)
            await conn.execute(
                "delete from extracted_tables where extraction_job_id=$1::uuid", job_id
            )
            for tbl in result.tables:
                # Анализ идёт по сетке с развёрнутыми объединениями, а хранится и
                # рисуется — исходная: объединение должно попасть в предпросмотр
                # как rowspan/colspan, а не размножиться по столбцам.
                filled = parsers.fill_merges(tbl.rows, tbl.merges)
                rect = analyze.detect_data_rect(tbl.rows, tbl.merges)
                header_rows = analyze.guess_header_rows(filled, rect)
                columns = analyze.analyze_columns(filled, header_rows, rect)
                confidences.extend(c.confidence for c in columns)
                preview = tbl.rows[:PREVIEW_ROWS]
                et = await conn.fetchrow(
                    "insert into extracted_tables(extraction_job_id, sheet_or_page, table_index, "
                    "row_count, column_count, header_rows, raw_preview, data, merges, data_rect) "
                    "values($1::uuid,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9::jsonb,$10::jsonb) returning id",
                    job_id, tbl.sheet_or_page, tbl.table_index,
                    tbl.row_count, tbl.column_count, header_rows,
                    json.dumps(preview, ensure_ascii=False),
                    json.dumps(tbl.rows, ensure_ascii=False),
                    json.dumps([list(m) for m in tbl.merges], ensure_ascii=False),
                    json.dumps(list(rect), ensure_ascii=False),
                )
                for col in columns:
                    await conn.execute(
                        "insert into extracted_columns(extracted_table_id, column_index, "
                        "source_header, inferred_type, confidence_score) "
                        "values($1,$2,$3,$4,$5)",
                        et["id"], col.column_index, col.source_header,
                        col.inferred_type, col.confidence,
                    )

    avg_conf = round(sum(confidences) / len(confidences), 4) if confidences else None
    # нет таблиц или есть предупреждения → нужна ручная проверка (needs_review)
    status = "succeeded" if result.tables and not result.warnings else "needs_review"
    async with pool.acquire() as conn:
        await conn.execute(
            "update extraction_jobs set status=$2::extraction_job_status, finished_at=now(), "
            "confidence_score=$3, warnings=$4::jsonb where id=$1::uuid",
            job_id, status, avg_conf,
            json.dumps(result.warnings, ensure_ascii=False),
        )
        await conn.execute(
            "update documents set status='extracted' where id=$1", job["document_id"]
        )


async def _fail(job_id: str, document_id, message: str) -> None:
    async with db.get_pool().acquire() as conn:
        await conn.execute(
            "update extraction_jobs set status='failed', finished_at=now(), error_message=$2 "
            "where id=$1::uuid",
            job_id, message,
        )
        await conn.execute(
            "update documents set status='uploaded' where id=$1", document_id
        )


async def enqueue_or_run(conn, document_version_id: str) -> str:
    """Создаёт extraction_job (или переиспользует) и возвращает его id."""
    row = await conn.fetchrow(
        "insert into extraction_jobs(document_version_id, status) "
        "values($1::uuid, 'queued') returning id",
        document_version_id,
    )
    return str(row["id"])
