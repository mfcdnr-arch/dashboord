"""HTTP: общая зона загрузки — приём файла без выбора папки и журнал импорта."""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from ... import db
from ..auth.deps import require_roles
from ..documents import service as doc_svc
from ..documents.router import _read_capped
from . import service

router = APIRouter(tags=["uploads"])
manage = require_roles("superadmin", "admin", "moderator")


@router.post("/uploads", status_code=status.HTTP_201_CREATED)
async def upload(file: UploadFile = File(...),
                 reporting_period_start: Optional[date] = Form(None),
                 force: bool = Form(False),
                 user: dict = Depends(manage)):
    """Принять файл, не спрашивая папку: её определит система после разбора.

    Дата, если её не указали, вычитывается из имени файла — у недельных форм она
    там есть. Не нашлась — отказываем: выдумать отчётную дату нельзя, по ней
    строится вся история показателя.
    """
    filename = doc_svc.safe_filename(file.filename)
    period = reporting_period_start or service.period_from_filename(filename)
    if period is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Не удалось определить отчётную дату по имени файла — укажите её.")
    content = await _read_capped(file, doc_svc.MAX_UPLOAD_BYTES)
    async with db.get_pool().acquire() as conn:
        folder_id = await service.inbox_folder(conn, user["organization_id"], user["id"])
        try:
            res = await doc_svc.save_document(
                conn, org_id=user["organization_id"], user_id=user["id"], folder_id=folder_id,
                filename=filename, content=content, content_type=file.content_type,
                period_start=period, force=force,
                # Распознавание здесь обязательно, а не по галочке папки: пока
                # файл не разобран, узнать его форму и разложить нельзя.
                enqueue=True)
        except doc_svc.UploadError as e:
            raise HTTPException(e.status_code, e.detail)
    res["period_guessed"] = reporting_period_start is None
    return res


@router.get("/uploads")
async def journal(limit: int = Query(service.JOURNAL_LIMIT, ge=1, le=200),
                  user: dict = Depends(manage)):
    """Журнал импорта: что загрузили, куда это уехало и почему."""
    async with db.get_pool().acquire() as conn:
        return {"items": await service.journal(conn, user["organization_id"], limit)}


@router.get("/uploads/known-forms")
async def known_forms(user: dict = Depends(manage)):
    """Подсказка: какие формы уже узнаются сами, а что уйдёт на ручную разметку."""
    async with db.get_pool().acquire() as conn:
        return {"items": await service.known_forms(conn, user["organization_id"])}


@router.post("/uploads/{document_id}/route")
async def route(document_id: str, folder_id: str = Form(...), user: dict = Depends(manage)):
    """Указать папку вручную — когда система форму не узнала."""
    async with db.get_pool().acquire() as conn:
        try:
            return await service.route_manually(
                conn, user["organization_id"], document_id, folder_id, user["id"])
        except LookupError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
