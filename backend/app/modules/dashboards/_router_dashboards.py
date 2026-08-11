"""HTTP: дашборды (CRUD/авто-сборка/шаблоны/публикация/версии) + страницы.

Вынесено из router.py. Дашборды/страницы создают admin/moderator; чтение —
любой авторизованный.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from ... import db
from ..audit import service as audit_svc
from ..auth.deps import get_current_user, require_roles
from . import service
from ._router_base import _bad, manage, superadmin_only
from .service import DashboardError

router = APIRouter()


class DashboardIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    folder_id: Optional[str] = None


class AutoIn(BaseModel):
    object_id: str
    name: Optional[str] = None


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None


class InstantiateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # Перепривязка кодов датасетов/метрик шаблона к кодам нового контекста
    # (старый код → новый). Пусто — использовать коды шаблона как есть.
    dataset_map: dict[str, str] = {}
    metric_map: dict[str, str] = {}


class PageIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None


class PagePatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class FolderMoveIn(BaseModel):
    folder_id: Optional[str] = None


# --- Дашборды ---
@router.post("/dashboards", status_code=status.HTTP_201_CREATED)
async def create_dashboard(body: DashboardIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.create_dashboard(conn, user["organization_id"], user["id"],
                                                  body.name, body.description, body.folder_id)
        except DashboardError as e:
            raise _bad(e)


@router.post("/dashboards/auto", status_code=status.HTTP_201_CREATED)
async def auto_build(body: AutoIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await service.auto_build(conn, user["organization_id"], user["id"], body.object_id, body.name)
        except DashboardError as e:
            raise _bad(e)


@router.get("/dashboards")
async def list_dashboards(user: dict = Depends(get_current_user), q: Optional[str] = None,
                          fav: bool = False, limit: int = Query(50, ge=1, le=200),
                          offset: int = Query(0, ge=0),
                          from_date: Optional[str] = None, to_date: Optional[str] = None,
                          folder_id: Optional[str] = None):
    async with db.acquire(user["id"]) as conn:
        return await service.list_dashboards(conn, user["organization_id"], user,
                                             q=q, fav_only=fav, limit=limit, offset=offset,
                                             from_date=from_date, to_date=to_date, folder_id=folder_id)


@router.post("/dashboards/{dashboard_id}/folder")
async def move_dashboard(dashboard_id: str, body: FolderMoveIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.set_folder(conn, user["organization_id"], dashboard_id, body.folder_id)
        except DashboardError as e:
            raise _bad(e)


@router.get("/dashboards/{dashboard_id}")
async def get_dashboard(dashboard_id: str, user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            result = await service.get_dashboard(conn, user["organization_id"], user, dashboard_id)
        except DashboardError as e:
            raise _bad(e)
        # лог просмотра (троттлинг внутри); не должен ломать открытие дашборда
        try:
            await audit_svc.log_view(conn, user["organization_id"], user["id"], dashboard_id)
        except Exception:
            pass
        return result


class DashboardPatch(BaseModel):
    """Частичная правка: передаём только то, что меняем."""

    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None


@router.patch("/dashboards/{dashboard_id}")
async def update_dashboard(dashboard_id: str, body: DashboardPatch, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                # exclude_unset: описание можно стереть (null), не трогая имя.
                return await service.update_dashboard(
                    conn, user["organization_id"], user, dashboard_id,
                    body.model_dump(exclude_unset=True),
                )
        except DashboardError as e:
            raise _bad(e)


@router.delete("/dashboards/{dashboard_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dashboard(dashboard_id: str, user: dict = Depends(superadmin_only)):
    async with db.acquire(user["id"]) as conn:
        try:
            await service.delete_dashboard(conn, user["organization_id"], user, dashboard_id)
        except DashboardError as e:
            raise _bad(e)


@router.post("/dashboards/{dashboard_id}/favorite")
async def add_favorite(dashboard_id: str, user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.set_favorite(conn, user["organization_id"], user, dashboard_id, True)
        except DashboardError as e:
            raise _bad(e)


@router.delete("/dashboards/{dashboard_id}/favorite")
async def remove_favorite(dashboard_id: str, user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.set_favorite(conn, user["organization_id"], user, dashboard_id, False)
        except DashboardError as e:
            raise _bad(e)


@router.get("/dashboard-templates")
async def list_templates(user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        return await service.list_templates(conn, user["organization_id"])


@router.get("/dashboard-templates/{template_id}/bindings")
async def template_bindings(template_id: str, user: dict = Depends(get_current_user)):
    """Коды датасетов/метрик, которые использует шаблон (для перепривязки при клоне)."""
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.template_bindings(conn, user["organization_id"], template_id)
        except DashboardError as e:
            raise _bad(e)


@router.post("/dashboard-templates/{template_id}/instantiate", status_code=status.HTTP_201_CREATED)
async def instantiate_template(template_id: str, body: InstantiateIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await service.create_from_template(
                    conn, user["organization_id"], user["id"], template_id, body.name,
                    body.dataset_map, body.metric_map)
        except DashboardError as e:
            raise _bad(e)


@router.post("/dashboards/{dashboard_id}/save-template", status_code=status.HTTP_201_CREATED)
async def save_template(dashboard_id: str, body: TemplateIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.save_as_template(
                conn, user["organization_id"], user["id"], dashboard_id, body.name, body.description)
        except DashboardError as e:
            raise _bad(e)


# Прямая публикация без модерации — только админ (override). Модераторы
# публикуют через одобрение заявки (POST /dashboards/{id}/moderate).
@router.post("/dashboards/{dashboard_id}/publish")
async def publish_dashboard(dashboard_id: str, user: dict = Depends(require_roles("admin", "superadmin"))):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await service.publish(conn, user["organization_id"], user["id"], dashboard_id)
        except DashboardError as e:
            raise _bad(e)


@router.post("/dashboards/{dashboard_id}/unpublish")
async def unpublish_dashboard(dashboard_id: str, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.unpublish(conn, user["organization_id"], dashboard_id)
        except DashboardError as e:
            raise _bad(e)


@router.get("/dashboards/{dashboard_id}/versions")
async def dashboard_versions(dashboard_id: str, user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.list_versions(conn, user["organization_id"], user, dashboard_id)
        except DashboardError as e:
            raise _bad(e)


@router.post("/dashboards/{dashboard_id}/versions/{version_no}/restore")
async def restore_dashboard_version(dashboard_id: str, version_no: int, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await service.restore_version(conn, user["organization_id"], user["id"], dashboard_id, version_no)
        except DashboardError as e:
            raise _bad(e)


@router.post("/dashboards/{dashboard_id}/pages", status_code=status.HTTP_201_CREATED)
async def create_page(dashboard_id: str, body: PageIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.create_page(conn, user["organization_id"], user["id"],
                                             dashboard_id, body.name, body.description)
        except DashboardError as e:
            raise _bad(e)


# --- Страницы ---
@router.patch("/dashboard-pages/{page_id}")
async def update_page(page_id: str, body: PagePatch, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.update_page(conn, user["organization_id"], page_id, body.name, body.description)
        except DashboardError as e:
            raise _bad(e)


@router.delete("/dashboard-pages/{page_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_page(page_id: str, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            await service.delete_page(conn, user["organization_id"], page_id)
        except DashboardError as e:
            raise _bad(e)
