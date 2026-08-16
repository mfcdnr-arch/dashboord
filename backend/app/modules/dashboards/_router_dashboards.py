"""HTTP: дашборды (CRUD/авто-сборка/шаблоны/публикация/версии) + страницы.

Вынесено из router.py. Дашборды/страницы создают admin/moderator; чтение —
любой авторизованный.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
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


class DatasetPick(BaseModel):
    """Что взять из одного набора данных. Пусто = всё."""

    fields: Optional[List[str]] = None      # какие показатели вообще берём
    blocks: Optional[List[str]] = None      # plan_fact | kpi | compare | dynamics | bar | table
    # Вид конкретного показателя: kpi | dynamics | both | none. Не задан —
    # система подбирает по роли столбца («за неделю» смотрят в движении,
    # накопительный итог — числом).
    views: Optional[Dict[str, str]] = None
    # Отчётные даты, для которых нужны ОТДЕЛЬНЫЕ страницы-срезы («Отчёт за
    # 05.08.2026»). Пусто — только сводные страницы, которые обновляются сами.
    periods: Optional[List[str]] = None


class AutoIn(BaseModel):
    object_id: str
    name: Optional[str] = None
    # Выбор мастера: {код набора: что из него взять}. Не передан — берём всё.
    selection: Optional[Dict[str, DatasetPick]] = None
    # Пересобрать существующий дашборд вместо создания нового: страницы и
    # виджеты заменяются, права доступа и обсуждение остаются.
    dashboard_id: Optional[str] = None
    # Коды расчётных показателей, отмеченных в мастере: они будут заведены
    # черновиками, и по каждому появится карточка.
    metrics: Optional[List[str]] = None
    # Проставлять ли пороги невыполнения плана (полоса «план и факт» и
    # спидометр «выполнение плана» краснеют ниже нормы). Пороги потом
    # правятся кнопкой ⚠ у самого виджета.
    alerts: bool = True

    def as_selection(self) -> Optional[dict]:
        if self.selection is None:
            return None
        return {code: pick.model_dump() for code, pick in self.selection.items()}


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None


class InstantiateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # Перепривязка кодов датасетов/метрик шаблона к кодам нового контекста
    # (старый код → новый). Пусто — использовать коды шаблона как есть.
    dataset_map: dict[str, str] = {}
    metric_map: dict[str, str] = {}
    # Перепривязка ПОЛЕЙ: у другого объекта коды показателей свои, они
    # выводятся из его заголовков. Обычно заполняется автоматически по именам
    # (см. /bindings?object_id=…), но можно передать и вручную.
    field_map: dict[str, str] = {}
    # Папка нового дашборда: тиражируя на другой объект, логично сразу класть
    # копию в его папку, а не оставлять «без папки».
    folder_id: Optional[str] = None


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


@router.post("/dashboards/auto/plan")
async def auto_build_plan(body: AutoIn, user: dict = Depends(manage)):
    """Что мастер соберёт при этом выборе — до того, как что-то создано.

    Считается ТЕМ ЖЕ планировщиком, что и сама сборка, поэтому «будет создано
    N виджетов» не может разойтись с результатом.
    """
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.auto_build_plan(
                conn, user["organization_id"], body.object_id, body.as_selection(), body.alerts)
        except DashboardError as e:
            raise _bad(e)


@router.post("/dashboards/auto", status_code=status.HTTP_201_CREATED)
async def auto_build(body: AutoIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await service.auto_build(
                    conn, user["organization_id"], user["id"], body.object_id, body.name,
                    selection=body.as_selection(), dashboard_id=body.dashboard_id,
                    metrics=body.metrics, alerts=body.alerts)
        except DashboardError as e:
            raise _bad(e)


class FeaturedIn(BaseModel):
    featured: bool
    order: Optional[int] = None


# ВАЖНО: статический путь объявлен ДО параметризованного `/dashboards/{id}` —
# Starlette матчит по порядку регистрации, иначе «featured» уедет в id.
@router.get("/dashboards/featured")
async def featured_dashboards(user: dict = Depends(get_current_user)):
    """Подборка «Руководителю»: что отмечено админом и доступно этому человеку."""
    async with db.acquire(user["id"]) as conn:
        return await service.list_featured(conn, user["organization_id"], user)


@router.post("/dashboards/{dashboard_id}/featured")
async def set_featured(dashboard_id: str, body: FeaturedIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.set_featured(conn, user["organization_id"], dashboard_id,
                                              body.featured, body.order)
        except DashboardError as e:
            raise _bad(e)


@router.get("/dashboards/{dashboard_id}/description-draft")
async def description_draft(dashboard_id: str, user: dict = Depends(manage)):
    """Черновик описания, собранный по составу дашборда.

    В БД молча не пишется: описание — обещание читателю, и сохранить его
    должен человек, посмотрев глазами.
    """
    async with db.acquire(user["id"]) as conn:
        return await service.describe_dashboard(conn, user["organization_id"], dashboard_id)


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
    # Подсказывать ли о показателях, которых нет на дашборде.
    suggest_new_fields: Optional[bool] = None


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
async def template_bindings(template_id: str, object_id: Optional[str] = None,
                            user: dict = Depends(get_current_user)):
    """Что использует шаблон и как это ляжет на другой объект.

    Без `object_id` — просто коды датасетов/метрик/полей шаблона. С ним —
    готовое сопоставление по ИМЕНАМ показателей плюс честный список того, что
    в целевом объекте не нашлось: тиражировать вслепую нельзя, неверно
    сопоставленный показатель выглядит рабочим и потому опаснее пустого.
    """
    async with db.acquire(user["id"]) as conn:
        try:
            if object_id:
                return await service.suggest_binding(
                    conn, user["organization_id"], template_id, object_id)
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
                    body.dataset_map, body.metric_map, body.field_map, body.folder_id)
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


class PlaceMetricIn(BaseModel):
    """Поставить карточку показателя на страницу дашборда."""

    page_id: str
    metric_code: str
    name: str
    unit: Optional[str] = None
    # Поля, на которых стоит формула: по ним ищется близкий по смыслу виджет,
    # рядом с которым логично встать.
    based_on: List[str] = []
    dataset_code: Optional[str] = None


@router.post("/dashboards/place-metric", status_code=status.HTTP_201_CREATED)
async def place_metric(body: PlaceMetricIn, user: dict = Depends(manage)):
    """Разместить показатель на дашборде рядом с близким по смыслу виджетом."""
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await service.place_metric_widget(
                    conn, user["organization_id"], user["id"], page_id=body.page_id,
                    metric_code=body.metric_code, name=body.name, unit=body.unit,
                    based_on=body.based_on, dataset_code=body.dataset_code)
        except DashboardError as e:
            raise _bad(e)


@router.get("/dashboards/{dashboard_id}/metrics")
async def dashboard_metrics(dashboard_id: str, user: dict = Depends(manage)):
    """Показатели, уже размещённые на дашборде: чтобы не предлагать их дважды."""
    async with db.get_pool().acquire() as conn:
        if not await service._can_view(conn, user["organization_id"], user, dashboard_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Дашборд не найден")
        return {"codes": await service.dashboard_metric_codes(conn, dashboard_id)}


@router.get("/dashboards/{dashboard_id}/freshness")
async def dashboard_freshness(dashboard_id: str, user: dict = Depends(get_current_user)):
    """Дата самых свежих данных под дашбордом — лёгкий запрос для автообновления.

    Открытая страница спрашивает раз в минуту и предлагает обновиться, если
    появился новый выпуск: иначе руководитель с незакрытой вкладкой смотрит на
    вчерашние числа и уверен, что они сегодняшние.
    """
    async with db.get_pool().acquire() as conn:
        if not await service._can_view(conn, user["organization_id"], user, dashboard_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Дашборд не найден")
        return await service.dashboard_freshness(conn, user["organization_id"], dashboard_id)


@router.get("/dashboards/{dashboard_id}/missing-fields")
async def dashboard_missing_fields(dashboard_id: str, user: dict = Depends(manage)):
    """Показатели, которые есть в данных, но не показаны на этом дашборде."""
    async with db.get_pool().acquire() as conn:
        if not await service._can_view(conn, user["organization_id"], user, dashboard_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Дашборд не найден")
        return await service.missing_dashboard_fields(conn, user["organization_id"], dashboard_id)


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
