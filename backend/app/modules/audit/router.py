"""Модуль «Аудит действий» (HTTP): чтение журнала изменений сущностей.

Журнал — чувствительная информация (кто что менял), поэтому доступ только у
администратора. Наполнение — триггерами БД; здесь только чтение.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel

from ... import db
from ...exports import to_csv, to_xlsx
from ..auth.deps import get_current_user, require_roles
from . import service
from .service import AuditError

router = APIRouter(tags=["audit"])
admin = require_roles("admin", "superadmin")
superadmin_only = require_roles("superadmin")


# Доступ к самому журналу аудита: superadmin — всегда; admin — только если
# superadmin явно выдал доступ (audit_access_grants). Управление грантами
# (ниже) — отдельная, более узкая зависимость superadmin_only.
async def audit_reader(user: dict = Depends(admin)) -> dict:
    if "superadmin" in user.get("roles", []):
        return user
    async with db.get_pool().acquire() as conn:
        if not await service.has_audit_access(conn, user["id"]):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Нет доступа к аудиту — обратитесь к суперадминистратору")
    return user

CSV_MEDIA = "text/csv; charset=utf-8"
XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _attach(name: str) -> dict:
    return {"Content-Disposition": f'attachment; filename="{name}"'}


class ClientExportIn(BaseModel):
    entity_type: str
    entity_id: str
    format: str


@router.post("/audit/log-export", status_code=status.HTTP_204_NO_CONTENT)
async def log_client_export(body: ClientExportIn, user: dict = Depends(get_current_user)):
    """Логирование выгрузок, сгенерированных НА КЛИЕНТЕ (PDF/PNG — jsPDF/html2canvas,
    без отдельного серверного эндпоинта). xlsx уже логируется на сервере."""
    async with db.get_pool().acquire() as conn:
        await service.write_event(conn, user["organization_id"], user["id"], "export",
                                  body.entity_type, body.entity_id, new_data={"format": body.format})


@router.get("/audit")
async def list_audit(
    user: dict = Depends(audit_reader),
    actor: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    action: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    include_views: bool = False,
    limit: int = Query(50, ge=1, le=service.MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    async with db.get_pool().acquire() as conn:
        try:
            return await service.list_events(
                conn, user["organization_id"], actor=actor, entity_type=entity_type,
                entity_id=entity_id, action=action, date_from=date_from, date_to=date_to,
                include_views=include_views, limit=limit, offset=offset)
        except AuditError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.get("/audit/export.csv")
async def export_audit_csv(
    user: dict = Depends(audit_reader), actor: Optional[str] = None, entity_type: Optional[str] = None,
    entity_id: Optional[str] = None, action: Optional[str] = None,
    date_from: Optional[str] = None, date_to: Optional[str] = None, include_views: bool = False,
):
    async with db.get_pool().acquire() as conn:
        try:
            headers, rows = await service.export_events(
                conn, user["organization_id"], actor=actor, entity_type=entity_type,
                entity_id=entity_id, action=action, date_from=date_from, date_to=date_to,
                include_views=include_views)
        except AuditError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return Response(to_csv(headers, rows), media_type=CSV_MEDIA, headers=_attach("audit.csv"))


@router.get("/audit/export.xlsx")
async def export_audit_xlsx(
    user: dict = Depends(audit_reader), actor: Optional[str] = None, entity_type: Optional[str] = None,
    entity_id: Optional[str] = None, action: Optional[str] = None,
    date_from: Optional[str] = None, date_to: Optional[str] = None, include_views: bool = False,
):
    async with db.get_pool().acquire() as conn:
        try:
            headers, rows = await service.export_events(
                conn, user["organization_id"], actor=actor, entity_type=entity_type,
                entity_id=entity_id, action=action, date_from=date_from, date_to=date_to,
                include_views=include_views)
        except AuditError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return Response(to_xlsx("Аудит", headers, rows), media_type=XLSX_MEDIA, headers=_attach("audit.xlsx"))



# --------------------------------------------------------------------------- #
# Управление доступом admin→аудит (только superadmin). ДО /audit/{event_id} —
# иначе literal-путь «access» перехватился бы параметром event_id.
# --------------------------------------------------------------------------- #
@router.get("/audit/access")
async def list_access(user: dict = Depends(superadmin_only)):
    async with db.get_pool().acquire() as conn:
        return await service.list_audit_access(conn, user["organization_id"])


@router.post("/audit/access/{target_user_id}")
async def grant_access(target_user_id: str, user: dict = Depends(superadmin_only)):
    async with db.get_pool().acquire() as conn:
        return await service.grant_audit_access(conn, user["id"], target_user_id)


@router.delete("/audit/access/{target_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_access(target_user_id: str, user: dict = Depends(superadmin_only)):
    async with db.get_pool().acquire() as conn:
        await service.revoke_audit_access(conn, target_user_id)


@router.get("/audit/{event_id}")
async def get_audit(event_id: str, user: dict = Depends(audit_reader)):
    async with db.get_pool().acquire() as conn:
        try:
            return await service.get_event(conn, user["organization_id"], event_id)
        except AuditError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
