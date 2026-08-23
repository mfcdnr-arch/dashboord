"""HTTP: доступ к дашборду — гранты, row-level RLS, комментарии, пресеты фильтров.

Вынесено из router.py.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from ... import db
from ..auth.deps import get_current_user
from . import service
from ._router_base import _bad, admin_only, manage
from .service import DashboardError

router = APIRouter()


# --- Доступ к дашборду (гранты) ---
class GrantIn(BaseModel):
    grantee_type: str
    role_id: Optional[str] = None
    user_id: Optional[str] = None
    scope: str = "dashboard"          # 'dashboard' (весь дашборд) | 'widget' (один виджет)
    widget_id: Optional[str] = None   # обязателен при scope='widget'


@router.get("/dashboards/{dashboard_id}/grants")
async def list_grants(dashboard_id: str, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return {"grants": await service.list_grants(conn, user["organization_id"], dashboard_id),
                    "targets": await service.grant_targets(conn, user["organization_id"]),
                    "widgets": await service.dashboard_widgets_flat(conn, user["organization_id"], dashboard_id)}
        except DashboardError as e:
            raise _bad(e)


@router.post("/dashboards/{dashboard_id}/grants", status_code=status.HTTP_201_CREATED)
async def add_grant(dashboard_id: str, body: GrantIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await service.add_grant(conn, user["organization_id"], user["id"], dashboard_id,
                                               body.grantee_type, body.role_id, body.user_id,
                                               scope=body.scope, widget_id=body.widget_id)
        except DashboardError as e:
            raise _bad(e)


@router.delete("/dashboards/{dashboard_id}/grants/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_grant(dashboard_id: str, grant_id: str, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                await service.remove_grant(conn, user["organization_id"], dashboard_id, grant_id, user["id"])
        except DashboardError as e:
            raise _bad(e)


# --- Доступ глазами пользователя: «что видит этот сотрудник» ---
# Живёт в модуле дашбордов (пишет в access_grants и переиспользует RLS), но
# отвечает по пути /users/... — так его находит карточка сотрудника в разделе
# «Пользователи». Корень /users уже проксируется, новых путей заводить не надо.
class UserAccessIn(BaseModel):
    grant: list[str] = []
    revoke: list[str] = []


@router.get("/users/{user_id}/dashboard-access")
async def user_dashboard_access(user_id: str, user: dict = Depends(admin_only)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.user_dashboard_access(conn, user["organization_id"], user_id)
        except DashboardError as e:
            raise _bad(e)


@router.post("/users/{user_id}/dashboard-access")
async def set_user_dashboard_access(user_id: str, body: UserAccessIn, user: dict = Depends(admin_only)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await service.set_user_dashboard_access(
                    conn, user["organization_id"], user["id"], user_id,
                    grant=body.grant, revoke=body.revoke)
        except DashboardError as e:
            raise _bad(e)


# --- Row-level RLS: доступ к строкам данных объекта по подразделению ---
class RowAclIn(BaseModel):
    row_labels: list[str] = []


@router.get("/objects/{object_id}/row-acl")
async def get_row_acl(object_id: str, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.get_row_acl(conn, user["organization_id"], object_id)
        except DashboardError as e:
            raise _bad(e)


@router.put("/objects/{object_id}/row-acl/{department_id}")
async def set_row_acl(object_id: str, department_id: str, body: RowAclIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.set_row_acl(conn, user["organization_id"], user["id"],
                                             object_id, department_id, body.row_labels)
        except DashboardError as e:
            raise _bad(e)


# --- Обсуждение дашборда (комментарии) ---
class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    # Привязка к конкретной цифре (п. 8). Пусто — замечание ко всему отчёту,
    # как было раньше; этот способ никуда не девается.
    widget_id: Optional[str] = None
    # Отчётная дата, которую человек ВИДЕЛ в момент написания: сервер не может
    # восстановить её постфактум (виджет мог быть отфильтрован периодом
    # страницы или закреплён за срезом), а без неё замечание через неделю
    # относилось бы к другому числу.
    period: Optional[str] = None
    row_label: Optional[str] = None


@router.get("/dashboards/{dashboard_id}/comments")
async def list_comments(dashboard_id: str, user: dict = Depends(get_current_user),
                        limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                        widget_id: Optional[str] = None):
    """Обсуждение отчёта. `widget_id` — лента ОДНОЙ цифры; без него отдаётся
    всё, включая замечания к цифрам, чтобы часть разговора не оказалась видна
    только тому, кто открыл нужный виджет."""
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.list_comments(conn, user["organization_id"], user, dashboard_id,
                                               limit=limit, offset=offset, widget_id=widget_id)
        except DashboardError as e:
            raise _bad(e)


@router.post("/dashboards/{dashboard_id}/comments", status_code=status.HTTP_201_CREATED)
async def add_comment(dashboard_id: str, body: CommentIn, user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await service.add_comment(
                    conn, user["organization_id"], user, dashboard_id, body.body,
                    widget_id=body.widget_id, period=body.period, row_label=body.row_label)
        except DashboardError as e:
            raise _bad(e)


@router.delete("/dashboards/{dashboard_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(dashboard_id: str, comment_id: str, user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                await service.delete_comment(conn, user["organization_id"], user, dashboard_id, comment_id)
        except DashboardError as e:
            raise _bad(e)


# --- Пресеты фильтров дашборда ---
class PresetIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    filters: Dict[str, Any] = {}


@router.get("/dashboards/{dashboard_id}/presets")
async def list_presets(dashboard_id: str, user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.list_presets(conn, user["organization_id"], user, dashboard_id)
        except DashboardError as e:
            raise _bad(e)


@router.post("/dashboards/{dashboard_id}/presets", status_code=status.HTTP_201_CREATED)
async def create_preset(dashboard_id: str, body: PresetIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.create_preset(conn, user["organization_id"], user["id"],
                                               dashboard_id, body.name, body.filters)
        except DashboardError as e:
            raise _bad(e)


@router.delete("/dashboards/{dashboard_id}/presets/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_preset(dashboard_id: str, preset_id: str, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            await service.delete_preset(conn, user["organization_id"], dashboard_id, preset_id)
        except DashboardError as e:
            raise _bad(e)
