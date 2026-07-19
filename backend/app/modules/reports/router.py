"""Модуль «Отчёты» (HTTP): системный мониторинг, посещаемость. Только admin."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ... import db
from ..auth.deps import require_roles
from . import service

router = APIRouter(prefix="/reports", tags=["reports"])
admin = require_roles("admin")


@router.get("/system")
async def system_report(user: dict = Depends(admin)):
    async with db.get_pool().acquire() as conn:
        return await service.system_health(conn)


@router.get("/attendance")
async def attendance_report(user: dict = Depends(admin)):
    async with db.get_pool().acquire() as conn:
        return await service.attendance(conn, user["organization_id"])
