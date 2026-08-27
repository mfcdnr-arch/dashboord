"""HTTP: раздел «Статистика услуг ДНР» (свод по отделениям МФЦ).

Отдельный раздел меню, а не дашборд: список отделений с раскрытием по
ведомству и услуге внутри строки — такого разреза обычный конструктор
виджетов не строит (см. docstring service.py).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ... import db
from ..auth.deps import get_current_user
from . import service

router = APIRouter(prefix="/dnr-stats", tags=["dnr-stats"])

_STAFF_ROLES = {"superadmin", "admin", "moderator"}


async def view_access(user: dict = Depends(get_current_user)) -> dict:
    """Раздел читают staff (как раньше) и пользователи-руководители, которым
    администратор включил «Руководителю» (`users.show_featured`) — то же
    решение, что уже открывает им подборку избранных дашбордов; второй
    системы допуска не заводим. Строк/офисов друг от друга не прячем — это
    инструмент сравнения отделений целиком, RLS по строкам здесь не применим."""
    if set(user.get("roles") or ()) & _STAFF_ROLES:
        return user
    if user.get("show_featured"):
        return user
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")


@router.get("/{object_id}/overview")
async def overview(object_id: str, user: dict = Depends(view_access)):
    async with db.get_pool().acquire() as conn:
        try:
            return await service.overview(conn, user["organization_id"], object_id)
        except service.DnrStatsError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))


@router.get("/{object_id}/offices")
async def offices(object_id: str, q: Optional[str] = None,
                  sort: str = Query("total_desc"), dept: Optional[str] = None,
                  user: dict = Depends(view_access)):
    async with db.get_pool().acquire() as conn:
        try:
            return await service.list_offices(conn, user["organization_id"], object_id,
                                              q=q, sort=sort, dept_filter=dept)
        except service.DnrStatsError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))


@router.get("/{object_id}/office-department")
async def office_department(object_id: str, office: str = Query(...), dept: str = Query(...),
                            user: dict = Depends(view_access)):
    """Дашборд одного ведомства для одного отделения (скрин 3). Отделение —
    ПАРАМЕТРОМ запроса, а не куском пути: адрес отделения длинный и содержит
    символы («», запятые), которым в пути делать нечего."""
    async with db.get_pool().acquire() as conn:
        try:
            return await service.office_department(conn, user["organization_id"], object_id, office, dept)
        except service.DnrStatsError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))


@router.get("/{object_id}/office-service")
async def office_service(object_id: str, office: str = Query(...), dept: str = Query(...),
                         idx: int = Query(..., ge=1), user: dict = Depends(view_access)):
    """Дашборд одной услуги для одного отделения (скрин 2)."""
    async with db.get_pool().acquire() as conn:
        try:
            return await service.office_service(conn, user["organization_id"], object_id, office, dept, idx)
        except service.DnrStatsError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
