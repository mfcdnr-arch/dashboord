"""Модуль «Отчёты» (HTTP): системный мониторинг, посещаемость. Только admin.

Период задаётся парой `from`/`to` (даты включительно) и по умолчанию равен
последним 30 дням. Выгрузка принимает те же параметры и считается тем же кодом,
что и экран, — иначе файл разошёлся бы с тем, что человек только что видел.

Очистка истории (`/history`) — отдельно и только суперадминистратору: она
удаляет данные, и право на это есть у владельца системы, а не у каждого
администратора.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel

from ... import db
from ...exports import to_csv, to_xlsx
from ..auth.deps import require_roles
from . import service

router = APIRouter(prefix="/reports", tags=["reports"])
admin = require_roles("admin", "superadmin")
# Очистка журналов необратима, поэтому — только владелец системы (то же
# правило, что у удаления дашбордов и показателей).
superadmin_only = require_roles("superadmin")

CSV_MEDIA = "text/csv; charset=utf-8"
XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _attach(name: str) -> dict:
    return {"Content-Disposition": f'attachment; filename="{name}"'}


@router.get("/system")
async def system_report(user: dict = Depends(admin)):
    async with db.get_pool().acquire() as conn:
        return await service.system_health(conn)


@router.get("/attendance")
async def attendance_report(user: dict = Depends(admin),
                            from_date: Optional[str] = Query(None, alias="from"),
                            to_date: Optional[str] = Query(None, alias="to")):
    async with db.get_pool().acquire() as conn:
        return await service.attendance(conn, user["organization_id"], from_date, to_date)


@router.get("/attendance/day")
async def attendance_day_report(date: str, user: dict = Depends(admin)):
    """Разбор одного дня графика: кто заходил и сколько раз."""
    async with db.get_pool().acquire() as conn:
        try:
            return await service.attendance_day(conn, user["organization_id"], date)
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.get("/popularity")
async def popularity_report(user: dict = Depends(admin),
                            from_date: Optional[str] = Query(None, alias="from"),
                            to_date: Optional[str] = Query(None, alias="to")):
    async with db.get_pool().acquire() as conn:
        return await service.popularity(conn, user["organization_id"], from_date, to_date)


@router.get("/popularity/viewers")
async def popularity_viewers(dashboard_id: str, user: dict = Depends(admin),
                             from_date: Optional[str] = Query(None, alias="from"),
                             to_date: Optional[str] = Query(None, alias="to")):
    async with db.get_pool().acquire() as conn:
        return await service.dashboard_viewers(conn, user["organization_id"], dashboard_id,
                                               from_date, to_date)


@router.get("/moderation")
async def moderation_report(user: dict = Depends(admin),
                            from_date: Optional[str] = Query(None, alias="from"),
                            to_date: Optional[str] = Query(None, alias="to")):
    async with db.get_pool().acquire() as conn:
        return await service.moderation_stats(conn, user["organization_id"], from_date, to_date)


@router.get("/data-quality")
async def data_quality_report(user: dict = Depends(admin)):
    async with db.get_pool().acquire() as conn:
        return await service.data_quality(conn, user["organization_id"])


@router.get("/business")
async def business_report(user: dict = Depends(admin)):
    async with db.get_pool().acquire() as conn:
        return await service.business(conn, user["organization_id"], user)


# --- Очистка истории (только суперадминистратор) ---
# ВАЖНО: статический путь объявлен ДО параметризованного `/{kind}/export.{fmt}`,
# иначе Starlette сматчит «history» как вид отчёта.
class PurgeIn(BaseModel):
    kinds: List[str] = []
    older_than_days: int = 180


@router.get("/history")
async def history_report(user: dict = Depends(superadmin_only),
                         older_than_days: int = Query(180, ge=0, le=3650)):
    """Сколько накопилось журналов и что из этого можно удалить."""
    async with db.get_pool().acquire() as conn:
        return await service.history_stats(conn, user["organization_id"], older_than_days)


@router.post("/history/purge")
async def history_purge(body: PurgeIn, user: dict = Depends(superadmin_only)):
    if not body.kinds:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Выберите, что удалять")
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await service.purge_history(conn, user["organization_id"], user["id"],
                                                   body.kinds, body.older_than_days)
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


# --- Выгрузка отчёта в файл ---
@router.get("/{kind}/export.{fmt}")
async def export_report(kind: str, fmt: str, user: dict = Depends(admin),
                        from_date: Optional[str] = Query(None, alias="from"),
                        to_date: Optional[str] = Query(None, alias="to")):
    if kind not in service.EXPORT_KINDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"Отчёт «{kind}» не выгружается. Доступны: {', '.join(service.EXPORT_KINDS)}")
    if fmt not in ("csv", "xlsx"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Формат: csv или xlsx")
    async with db.acquire(user["id"]) as conn:
        sheet, headers, rows = await service.export_report(
            conn, user["organization_id"], user, kind, from_date, to_date)
        # Выгрузка — тоже действие, за которое кто-то отвечает: пишем в аудит
        # тем же событием, что и выгрузки дашбордов.
        try:
            from ..audit import service as audit_svc
            await audit_svc.write_event(conn, user["organization_id"], user["id"], "export",
                                        "system", str(user["organization_id"]),
                                        new_data={"report": kind, "format": fmt})
        except Exception:  # noqa: BLE001 — журнал не должен ломать выгрузку
            pass
    name = f"report-{kind}.{fmt}"
    if fmt == "csv":
        return Response(to_csv(headers, rows), media_type=CSV_MEDIA, headers=_attach(name))
    return Response(to_xlsx(sheet, headers, rows), media_type=XLSX_MEDIA, headers=_attach(name))
