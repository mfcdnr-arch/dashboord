"""Сохранение загруженного документа — общий код папок и общей зоны загрузки.

Вынесено из `router.py`, когда появилась зона «Загрузка» (шаг ⑤): там файл
кладут, не выбирая папку, а система разбирает его и раскладывает сама. Путь
сохранения при этом обязан быть ОДИН: проверка дублей, запись в MinIO,
транзакция «документ + версия» и постановка распознавания — всё то, что
накапливалось правками с 06.08 по 15.08, копией разошлось бы при первой же
следующей правке.
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Optional

from fastapi.concurrency import run_in_threadpool

from ..ingestion import queue
from ..ingestion import service as ing_service
from . import storage

log = logging.getLogger(__name__)

ALLOWED = {"xlsx", "xls", "csv", "pdf", "docx"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 МБ (в дополнение к nginx client_max_body_size)


class UploadError(Exception):
    """Ошибка загрузки с готовым HTTP-кодом и полезной нагрузкой для интерфейса."""

    def __init__(self, status_code: int, detail):
        super().__init__(detail if isinstance(detail, str) else str(detail))
        self.status_code = status_code
        self.detail = detail


def safe_filename(raw: Optional[str]) -> str:
    """Только базовое имя: «../../evil.xlsx» уезжало в ключ объекта MinIO."""
    return os.path.basename((raw or "file").replace("\\", "/")).strip() or "file"


def file_ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


async def find_duplicate(conn, org_id, checksum: str) -> Optional[dict]:
    """Тот же файл (побайтово) уже загружен в организацию?

    Ищем по ВСЕЙ организации, а не по текущей папке: файл, положенный второй раз
    в соседнюю папку, — тот же дубль, просто найти его потом ещё труднее.
    """
    row = await conn.fetchrow(
        "select d.id, d.original_filename, d.reporting_period_start, d.created_at, "
        "f.name as folder_name, o.name as object_name, "
        "exists(select 1 from dataset_releases r where r.source_document_version_id=v.id) as released "
        "from document_versions v join documents d on d.id=v.document_id "
        "left join folders f on f.id=d.folder_id left join objects o on o.id=f.object_id "
        "where d.organization_id=$1 and v.checksum=$2 order by d.created_at limit 1",
        org_id, checksum)
    if row is None:
        return None
    return {"document_id": str(row["id"]), "filename": row["original_filename"],
            "folder_name": row["folder_name"], "object_name": row["object_name"],
            "reporting_period_start": str(row["reporting_period_start"]),
            "uploaded_at": row["created_at"].isoformat() if row["created_at"] else None,
            "released": row["released"]}


def duplicate_message(dup: dict) -> str:
    where = " / ".join(x for x in (dup["object_name"], dup["folder_name"]) if x)
    return ("Этот файл уже загружен: «" + dup["filename"] + "»"
            + (f" (📁 {where})" if where else "")
            + f", отчётный период {dup['reporting_period_start']}"
            + (", данные из него уже выпущены" if dup["released"] else "")
            + ". Содержимое совпадает побайтово.")


async def save_document(conn, *, org_id, user_id, folder_id: str, filename: str, content: bytes,
                        content_type: Optional[str], period_start, period_end=None,
                        force: bool = False, routed_by: Optional[str] = None,
                        routed_note: Optional[str] = None, enqueue: Optional[bool] = None) -> dict:
    """Документ + версия + файл в хранилище + постановка распознавания.

    `enqueue=None` — решает папка (её галочка «готовить автоматически»): бывают
    папки, куда файлы складывают на хранение. Зона загрузки передаёт True явно:
    файл там ещё не в своей папке, и не распознав его, разложить нельзя.
    """
    ext = file_ext(filename)
    if ext not in ALLOWED:
        raise UploadError(400, f"Неподдерживаемый формат: .{ext}. Разрешены: {', '.join(sorted(ALLOWED))}")
    if not content:
        raise UploadError(400, "Пустой файл")
    checksum = hashlib.sha256(content).hexdigest()

    if not force:
        # Дубль — предупреждение, а не запрет: бывает, что тот же файл заводят
        # повторно осознанно. Решение принимает человек кнопкой «всё равно
        # загрузить»; молча пропускать нельзя — из дубля так же молча выпустят
        # вторые данные за тот же период.
        dup = await find_duplicate(conn, org_id, checksum)
        if dup is not None:
            raise UploadError(409, {"message": duplicate_message(dup), "duplicate": dup})

    # Одна транзакция на документ + версию + запись в хранилище: сбой записи в
    # MinIO не должен оставлять в БД «документ без версии» — такой документ
    # виден в списке, но его нельзя ни скачать, ни распознать.
    async with conn.transaction():
        doc = await conn.fetchrow(
            "insert into documents(organization_id, folder_id, original_filename, source_type, "
            "reporting_period_start, reporting_period_end, period_confirmed_by, period_confirmed_at, "
            "uploaded_by, routed_by, routed_note, routed_at) "
            "values($1,$2::uuid,$3,$4::document_source_type,$5,$6,$7,now(),$7,$8,$9,"
            "  case when $8::text is null then null else now() end) returning id",
            org_id, folder_id, filename, ext, period_start, period_end, user_id,
            routed_by, routed_note)
        doc_id = doc["id"]
        object_name = f"{folder_id}/{doc_id}/v1/{filename}"
        try:
            storage_path = await run_in_threadpool(
                storage.put_object, object_name, content,
                content_type or "application/octet-stream")
        except Exception as e:  # хранилище недоступно/отвергло имя объекта
            raise UploadError(502, f"Не удалось сохранить файл в хранилище: {e}")
        ver = await conn.fetchrow(
            "insert into document_versions(document_id, version_no, storage_path, checksum, "
            "file_size_bytes, uploaded_by) values($1,1,$2,$3,$4,$5) returning id",
            doc_id, storage_path, checksum, len(content), user_id)

    # Распознавание запускаем САМИ: раньше его отдельным вызовом делал интерфейс,
    # и файл, залитый мимо формы, оставался нераспознанным навсегда. Сбой очереди
    # не проваливает загрузку — файл уже в хранилище, а повисшие задания добирает
    # ежедневное задание воркера.
    job_id = None
    want = enqueue
    if want is None:
        want = bool(await conn.fetchval("select auto_prepare from folders where id=$1::uuid", folder_id))
    if want:
        try:
            job_id = await ing_service.enqueue_or_run(conn, str(ver["id"]))
            await queue.enqueue_extraction(job_id)
        except Exception as exc:  # noqa: BLE001 — очередь недоступна
            log.warning("Не удалось поставить распознавание документа %s: %s", doc_id, exc)

    return {"extraction_job_id": job_id, "id": str(doc_id), "original_filename": filename,
            "source_type": ext, "size": len(content),
            "reporting_period_start": str(period_start) if period_start else None,
            "storage_path": storage_path, "version_id": str(ver["id"])}
