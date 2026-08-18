"""Инструкции и объявления (HTTP).

Читают все авторизованные — это и есть смысл раздела. Пишут admin/moderator:
инструкция и объявление видны всей организации, поэтому право на них такое же,
как на публикацию отчёта.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field

from ... import db
from ..audit import service as audit_svc
from ..auth.deps import get_current_user, require_roles
from ..documents import storage
from . import service
from .service import PortalError

router = APIRouter(tags=["portal"])
manage = require_roles("superadmin", "admin", "moderator")

# Инструкцию открывают в браузере, поэтому ограничиваем теми форматами, которые
# он безопасно покажет или скачает: исполняемое в систему попадать не должно.
ALLOWED = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
}
MAX_FILE_MB = 25


def _bad(e: PortalError) -> HTTPException:
    code = status.HTTP_404_NOT_FOUND if "не найден" in str(e) else status.HTTP_400_BAD_REQUEST
    return HTTPException(code, str(e))


class InstructionIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    section: Optional[str] = None
    body: Optional[str] = None
    position: int = 0
    is_published: bool = True


class InstructionPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=300)
    section: Optional[str] = None
    body: Optional[str] = None
    position: Optional[int] = None
    is_published: Optional[bool] = None


@router.get("/instructions")
async def list_instructions(q: Optional[str] = None, drafts: bool = False,
                            user: dict = Depends(get_current_user)):
    """Список инструкций. Черновики — только управляющим и по явному запросу."""
    async with db.get_pool().acquire() as conn:
        include_drafts = drafts and await _can_manage(conn, user)
        return await service.list_instructions(
            conn, user["organization_id"], user["id"], include_drafts=include_drafts, q=q)


@router.get("/instructions/{instruction_id}")
async def get_instruction(instruction_id: str, user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        try:
            # Открытие отмечает инструкцию прочитанной — на этом держится «новое».
            return await service.get_instruction(
                conn, user["organization_id"], instruction_id, user["id"],
                allow_draft=await _can_manage(conn, user))
        except PortalError as e:
            raise _bad(e)


@router.get("/instructions/{instruction_id}/file")
async def download_instruction_file(instruction_id: str, user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        try:
            f = await service.file_of(conn, user["organization_id"], instruction_id,
                                      allow_draft=await _can_manage(conn, user))
        except PortalError as e:
            raise _bad(e)
    data = storage.get_object(f["path"])
    name = (f["name"] or "instruction").replace('"', "")
    return Response(
        content=data, media_type="application/octet-stream",
        # filename* — чтобы кириллица в имени не превращалась в кракозябры.
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{name}"},
    )


@router.post("/instructions", status_code=status.HTTP_201_CREATED)
async def create_instruction(body: InstructionIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.create_instruction(
                conn, user["organization_id"], user["id"], body.model_dump())
        except PortalError as e:
            raise _bad(e)


@router.patch("/instructions/{instruction_id}")
async def update_instruction(instruction_id: str, body: InstructionPatch, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.update_instruction(
                conn, user["organization_id"], instruction_id, body.model_dump(exclude_unset=True))
        except PortalError as e:
            raise _bad(e)


@router.post("/instructions/{instruction_id}/file")
async def upload_instruction_file(instruction_id: str, file: UploadFile = File(...),
                                  user: dict = Depends(manage)):
    """Приложить готовое руководство. Файл кладётся в то же хранилище, что и отчёты."""
    name = (file.filename or "file").split("/")[-1].split("\\")[-1]
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if ext not in ALLOWED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Такой формат приложить нельзя. Допустимы: " + ", ".join(sorted(ALLOWED)))
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Файл пустой")
    if len(data) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Файл больше {MAX_FILE_MB} МБ")
    path = storage.put_object(f"instructions/{instruction_id}/{name}", data, ALLOWED[ext])
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.set_file(conn, user["organization_id"], instruction_id,
                                          path, name, len(data))
        except PortalError as e:
            raise _bad(e)


@router.delete("/instructions/{instruction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_instruction(instruction_id: str, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            path = await service.delete_instruction(conn, user["organization_id"], instruction_id)
        except PortalError as e:
            raise _bad(e)
    if path:
        # Осечка удаления файла не должна проваливать операцию: сирота в
        # хранилище безобиднее, чем инструкция, которая «не удаляется».
        try:
            storage.remove_object(path)
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- #
# Объявления
# --------------------------------------------------------------------------- #

class AnnouncementIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1)
    important: bool = False
    ends_at: Optional[str] = None


class AnnouncementPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=300)
    body: Optional[str] = None
    important: Optional[bool] = None
    is_active: Optional[bool] = None
    ends_at: Optional[str] = None


@router.get("/announcements")
async def list_announcements(all: bool = False, user: dict = Depends(get_current_user)):
    """Действующие объявления. `all=true` (управляющим) — включая истёкшие."""
    async with db.get_pool().acquire() as conn:
        only_active = not (all and await _can_manage(conn, user))
        return await service.list_announcements(conn, user["organization_id"], only_active=only_active)


@router.post("/announcements", status_code=status.HTTP_201_CREATED)
async def create_announcement(body: AnnouncementIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                a = await service.create_announcement(
                    conn, user["organization_id"], user["id"], body.model_dump())
                # Объявление видит вся организация — событие значимое, оно должно
                # быть в журнале наравне с публикацией отчёта.
                await audit_svc.write_event(
                    conn, user["organization_id"], user["id"], "create", "announcement", a["id"],
                    new_data={"title": a["title"], "important": a["important"], "ends_at": a["ends_at"]})
                return a
        except PortalError as e:
            raise _bad(e)


@router.patch("/announcements/{announcement_id}")
async def update_announcement(announcement_id: str, body: AnnouncementPatch, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.update_announcement(
                conn, user["organization_id"], announcement_id, body.model_dump(exclude_unset=True))
        except PortalError as e:
            raise _bad(e)


@router.delete("/announcements/{announcement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_announcement(announcement_id: str, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            await service.delete_announcement(conn, user["organization_id"], announcement_id)
        except PortalError as e:
            raise _bad(e)


async def _can_manage(conn, user: dict) -> bool:
    """Управляющий ли это. Роли читаем из БД: в токене их нет."""
    return bool(await conn.fetchval(
        "select 1 from user_roles ur join roles r on r.id=ur.role_id "
        "where ur.user_id=$1 and r.code in ('superadmin','admin','moderator') limit 1", user["id"]))
