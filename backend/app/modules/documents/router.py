"""Модуль «Документы»: загрузка файлов в папки (MinIO) и их список.

Отчётная дата указывается вручную при загрузке (решение по проекту).
Форматы v1: xlsx, xls, csv, pdf, docx.
"""
from __future__ import annotations

import hashlib
import os
from datetime import date
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.concurrency import run_in_threadpool

from ... import db
from ..auth.deps import get_current_user, require_roles
from . import storage

router = APIRouter(tags=["documents"])
manage = require_roles("admin", "moderator")

ALLOWED = {"xlsx", "xls", "csv", "pdf", "docx"}
MAX_DOCS_LIMIT = 200
# Серверный лимит размера загружаемого документа (в дополнение к nginx
# client_max_body_size). Читаем чанками с ранним обрывом, чтобы ограничить
# память даже при прямом доступе к API (без прокси).
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 МБ


async def _read_capped(file, limit: int) -> bytes:
    """Читает UploadFile по частям; при превышении limit — HTTP 413."""
    buf = bytearray()
    while chunk := await file.read(1024 * 1024):
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"Файл слишком большой. Максимум {limit // (1024 * 1024)} МБ.",
            )
    return bytes(buf)


async def _folder_in_org(conn, folder_id: str, org_id) -> bool:
    return bool(
        await conn.fetchval(
            "select 1 from folders where id=$1::uuid and organization_id=$2",
            folder_id, org_id,
        )
    )


@router.post("/folders/{folder_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    folder_id: str,
    file: UploadFile = File(...),
    reporting_period_start: date = Form(...),
    reporting_period_end: Optional[date] = Form(None),
    user: dict = Depends(manage),
):
    # Имя файла приходит от клиента: берём ТОЛЬКО базовое имя. Иначе браузер или
    # самодельный клиент может прислать «../../evil.xlsx», и такие сегменты уедут
    # в ключ объекта MinIO (minio-py их отвергает — получался сырой 500, а строка
    # documents к тому моменту уже была вставлена → «документ без версии»).
    filename = os.path.basename((file.filename or "file").replace("\\", "/")).strip() or "file"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Неподдерживаемый формат: .{ext}. Разрешены: {', '.join(sorted(ALLOWED))}",
        )
    content = await _read_capped(file, MAX_UPLOAD_BYTES)
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустой файл")
    checksum = hashlib.sha256(content).hexdigest()

    async with db.get_pool().acquire() as conn:
        if not await _folder_in_org(conn, folder_id, user["organization_id"]):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Папка не найдена")
        # Одна транзакция на документ + версию + запись в хранилище: сбой записи
        # в MinIO не должен оставлять в БД «документ без версии» (такой документ
        # виден в списке, но его нельзя ни скачать, ни отправить на распознавание).
        async with conn.transaction():
            doc = await conn.fetchrow(
                "insert into documents(organization_id, folder_id, original_filename, source_type, "
                "reporting_period_start, reporting_period_end, period_confirmed_by, period_confirmed_at, uploaded_by) "
                "values($1,$2::uuid,$3,$4::document_source_type,$5,$6,$7,now(),$7) returning id",
                user["organization_id"], folder_id, filename, ext,
                reporting_period_start, reporting_period_end, user["id"],
            )
            doc_id = doc["id"]
            object_name = f"{folder_id}/{doc_id}/v1/{filename}"
            try:
                storage_path = await run_in_threadpool(
                    storage.put_object, object_name, content,
                    file.content_type or "application/octet-stream",
                )
            except Exception as e:  # хранилище недоступно/отвергло имя объекта
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    f"Не удалось сохранить файл в хранилище: {e}",
                )
            ver = await conn.fetchrow(
                "insert into document_versions(document_id, version_no, storage_path, checksum, file_size_bytes, uploaded_by) "
                "values($1,1,$2,$3,$4,$5) returning id",
                doc_id, storage_path, checksum, len(content), user["id"],
            )
    return {
        "id": str(doc_id),
        "original_filename": filename,
        "source_type": ext,
        "size": len(content),
        "reporting_period_start": str(reporting_period_start),
        "storage_path": storage_path,
        "version_id": str(ver["id"]),
    }


@router.get("/folders/{folder_id}/documents")
async def list_documents(
    folder_id: str,
    limit: int = Query(50, ge=1, le=MAX_DOCS_LIMIT),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
):
    """Постранично: {total, limit, offset, items}. Сортировка — новые сверху.

    Пагинация нужна, чтобы папка с тысячами документов не выгружалась целиком
    на каждый заход. Индексы ix_documents_folder_created / ix_document_versions_doc
    (миграция 022) держат запрос на диапазоне без полного скана.
    """
    async with db.get_pool().acquire() as conn:
        if not await _folder_in_org(conn, folder_id, user["organization_id"]):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Папка не найдена")
        total = await conn.fetchval(
            "select count(*) from documents where folder_id=$1::uuid", folder_id
        )
        rows = await conn.fetch(
            "select d.id, d.original_filename, d.source_type, d.status, "
            "d.reporting_period_start, d.reporting_period_end, d.created_at, "
            "v.id as version_id, v.file_size_bytes as size "
            "from documents d "
            "left join lateral (select id, file_size_bytes from document_versions v "
            "  where v.document_id=d.id order by version_no desc limit 1) v on true "
            "where d.folder_id=$1::uuid order by d.created_at desc limit $2 offset $3",
            folder_id, limit, offset,
        )
    return {"total": total, "limit": limit, "offset": offset, "items": [dict(r) for r in rows]}
