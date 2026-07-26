"""Модуль «Дашборды» (HTTP): дашборды, страницы, виджеты, данные виджета.

Дашборды/страницы/виджеты создают admin/moderator; чтение — любой авторизованный.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from ... import db
from ..audit import service as audit_svc
from ..auth.deps import get_current_user, require_roles
from . import service
from .service import DashboardError

router = APIRouter(tags=["dashboards"])
manage = require_roles("admin", "moderator")


def _bad(e: DashboardError) -> HTTPException:
    msg = str(e)
    code = status.HTTP_404_NOT_FOUND if "не найден" in msg else status.HTTP_400_BAD_REQUEST
    return HTTPException(code, msg)


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


class PageIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None


class PagePatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class WidgetIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    widget_type: str
    config: Dict[str, Any] = {}
    position_x: int = 0
    position_y: int = 0
    width: int = 4
    height: int = 3


class WidgetPatch(BaseModel):
    name: Optional[str] = None
    widget_type: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    position_x: Optional[int] = None
    position_y: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None


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
                          offset: int = Query(0, ge=0)):
    async with db.acquire(user["id"]) as conn:
        return await service.list_dashboards(conn, user["organization_id"], user,
                                             q=q, fav_only=fav, limit=limit, offset=offset)


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


@router.get("/dashboards/{dashboard_id}/comments")
async def list_comments(dashboard_id: str, user: dict = Depends(get_current_user),
                        limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.list_comments(conn, user["organization_id"], user, dashboard_id,
                                               limit=limit, offset=offset)
        except DashboardError as e:
            raise _bad(e)


@router.post("/dashboards/{dashboard_id}/comments", status_code=status.HTTP_201_CREATED)
async def add_comment(dashboard_id: str, body: CommentIn, user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await service.add_comment(conn, user["organization_id"], user, dashboard_id, body.body)
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


@router.get("/dashboard-templates")
async def list_templates(user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        return await service.list_templates(conn, user["organization_id"])


@router.post("/dashboard-templates/{template_id}/instantiate", status_code=status.HTTP_201_CREATED)
async def instantiate_template(template_id: str, body: InstantiateIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await service.create_from_template(conn, user["organization_id"], user["id"], template_id, body.name)
        except DashboardError as e:
            raise _bad(e)


@router.post("/dashboards/{dashboard_id}/save-template", status_code=status.HTTP_201_CREATED)
async def save_template(dashboard_id: str, body: TemplateIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.save_as_template(conn, user["organization_id"], user["id"], dashboard_id, body.name, body.description)
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


@router.get("/dashboard-pages/{page_id}/export.xlsx")
async def export_page_xlsx(page_id: str, user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            data = await service.export_page_xlsx(conn, user["organization_id"], user, page_id)
        except DashboardError as e:
            raise _bad(e)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="dashboard-page.xlsx"'},
    )


@router.get("/dashboard-pages/{page_id}/widgets")
async def list_widgets(page_id: str, user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.list_page_widgets(conn, user["organization_id"], page_id, user)
        except DashboardError as e:
            raise _bad(e)


@router.get("/dashboard-pages/{page_id}/data")
async def page_data(page_id: str, user: dict = Depends(get_current_user),
                    from_: Optional[str] = Query(None, alias="from"),
                    to: Optional[str] = Query(None),
                    row: Optional[str] = Query(None)):
    """Данные всех виджетов страницы за 1 запрос (перф). Учитывает фильтры страницы."""
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.compute_page_data(conn, user["organization_id"], page_id, user, from_, to, row)
        except DashboardError as e:
            raise _bad(e)


@router.post("/dashboard-pages/{page_id}/widgets", status_code=status.HTTP_201_CREATED)
async def create_widget(page_id: str, body: WidgetIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.create_widget(
                conn, user["organization_id"], user["id"], page_id, body.name, body.widget_type,
                body.config, {"position_x": body.position_x, "position_y": body.position_y,
                              "width": body.width, "height": body.height})
        except DashboardError as e:
            raise _bad(e)


# --- Виджеты ---
class WidgetPreviewIn(BaseModel):
    widget_type: str
    name: Optional[str] = None
    config: Dict[str, Any] = {}


@router.post("/widgets/preview")
async def preview_widget(body: WidgetPreviewIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.preview_widget(conn, user["organization_id"], body.widget_type, body.name, body.config)
        except DashboardError as e:
            raise _bad(e)


@router.get("/widgets/suggestions")
async def widget_suggestions(dataset_code: str, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.suggest_widgets(conn, user["organization_id"], dataset_code)
        except DashboardError as e:
            raise _bad(e)


@router.patch("/widgets/{widget_id}")
async def update_widget(widget_id: str, body: WidgetPatch, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.update_widget(conn, user["organization_id"], widget_id,
                                               body.model_dump(exclude_none=True))
        except DashboardError as e:
            raise _bad(e)


@router.delete("/widgets/{widget_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_widget(widget_id: str, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            await service.delete_widget(conn, user["organization_id"], widget_id)
        except DashboardError as e:
            raise _bad(e)


@router.get("/widgets/{widget_id}/data")
async def widget_data(widget_id: str, user: dict = Depends(get_current_user),
                      from_: Optional[str] = Query(None, alias="from"),
                      to: Optional[str] = Query(None),
                      row: Optional[str] = Query(None)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.compute_widget_data(conn, user["organization_id"], widget_id, from_, to, row, user)
        except DashboardError as e:
            raise _bad(e)


@router.get("/widgets/{widget_id}/drill")
async def widget_drill(widget_id: str, user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.widget_drill(conn, user["organization_id"], widget_id, user)
        except DashboardError as e:
            raise _bad(e)
