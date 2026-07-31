"""Модуль «Метрики» (HTTP): показатели, версии формул, предпросмотр.

- POST /metrics                         — создать метрику (admin/moderator)
- GET  /metrics                         — список метрик
- GET  /metrics/{id}                    — метрика + версии
- POST /metrics/{id}/versions           — создать версию формулы (draft)
- POST /metrics/versions/{vid}/validate — черновик → проверена
- POST /metrics/versions/{vid}/approve  — проверена → одобрена (не своя)
- GET  /metrics/versions/{vid}/value    — вычислить значение версии
- POST /metrics/preview                 — предпросмотр формулы на реальных данных
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ... import db
from ..auth.deps import get_current_user, require_roles
from .service import (
    MetricError,
    create_metric,
    create_version,
    evaluate_version,
    list_data_sources,
    preview,
    set_status,
    update_metric,
)

router = APIRouter(prefix="/metrics", tags=["metrics"])
manage = require_roles("admin", "moderator")


class MetricIn(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    owner_id: Optional[str] = None


class MetricPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    info_text: Optional[str] = None  # расширенная информация (FR-5.9)
    owner_id: Optional[str] = None


class VersionIn(BaseModel):
    formula: str = Field(min_length=1)
    unit: Optional[str] = None
    grain: Optional[str] = None
    calculation_type: str = "aggregate"


class PreviewIn(BaseModel):
    formula: str = Field(min_length=1)


def _bad(e: MetricError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_metric(body: MetricIn, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        try:
            return await create_metric(conn, user["organization_id"], user["id"],
                                       body.code, body.name, body.description, body.owner_id)
        except MetricError as e:
            raise _bad(e)


@router.get("")
async def list_metrics(user: dict = Depends(get_current_user), q: Optional[str] = None,
                       limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    """Постранично: {total, limit, offset, items}. q — поиск по коду/названию (ilike).
    Пикеры (напр. выбор KPI на «Главной») запрашивают большой limit и читают items."""
    where = "m.organization_id=$1"
    params: list = [user["organization_id"]]
    if q and q.strip():
        params.append(f"%{q.strip()}%")
        where += f" and (m.code ilike ${len(params)} or m.name ilike ${len(params)})"
    async with db.get_pool().acquire() as conn:
        total = await conn.fetchval(f"select count(*) from metrics m where {where}", *params)
        rows = await conn.fetch(
            "select m.id, m.code, m.name, m.description, m.created_at, "
            "(select count(*) from metric_versions v where v.metric_id=m.id) as versions, "
            "(select mv.unit from metric_versions mv where mv.metric_id=m.id and mv.status='approved' "
            " order by mv.version_no desc limit 1) as unit, "
            "exists(select 1 from metric_versions v where v.metric_id=m.id and v.status='approved') as has_approved "
            f"from metrics m where {where} order by m.name limit ${len(params) + 1} offset ${len(params) + 2}",
            *params, limit, offset,
        )
    return {"total": total, "limit": limit, "offset": offset, "items": [dict(r) for r in rows]}


@router.get("/data-sources")
async def data_sources(user: dict = Depends(manage)):
    """Списки для визуального конструктора: датасеты (поля/строки/даты) + метрики.
    Определён ДО /{metric_id}, иначе тот перехватит путь."""
    async with db.get_pool().acquire() as conn:
        return await list_data_sources(conn, user["organization_id"])


@router.get("/{metric_id}")
async def get_metric(metric_id: str, user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        m = await conn.fetchrow(
            "select id, code, name, description, info_text, created_at from metrics "
            "where id=$1::uuid and organization_id=$2", metric_id, user["organization_id"]
        )
        if m is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Метрика не найдена")
        versions = await conn.fetch(
            "select id, version_no, status, formula_expression, unit, grain, calculation_type, "
            "created_by, approved_by, approved_at, created_at "
            "from metric_versions where metric_id=$1::uuid order by version_no desc", metric_id
        )
    return {"metric": dict(m), "versions": [dict(v) for v in versions]}


@router.patch("/{metric_id}")
async def patch_metric(metric_id: str, body: MetricPatch, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        try:
            return await update_metric(conn, user["organization_id"], metric_id,
                                       body.name, body.description, body.info_text, body.owner_id)
        except MetricError as e:
            raise _bad(e)


@router.post("/{metric_id}/versions", status_code=status.HTTP_201_CREATED)
async def add_version(metric_id: str, body: VersionIn, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        try:
            async with conn.transaction():
                return await create_version(conn, user["organization_id"], user["id"], metric_id,
                                            body.formula, body.unit, body.grain, body.calculation_type)
        except MetricError as e:
            raise _bad(e)


@router.post("/versions/{version_id}/validate")
async def validate_version(version_id: str, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        try:
            return await set_status(conn, user["organization_id"], user["id"], version_id, "validated")
        except MetricError as e:
            raise _bad(e)


@router.post("/versions/{version_id}/approve")
async def approve_version(version_id: str, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        try:
            async with conn.transaction():
                return await set_status(conn, user["organization_id"], user["id"], version_id, "approved")
        except MetricError as e:
            raise _bad(e)


@router.get("/versions/{version_id}/value")
async def version_value(version_id: str, user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        try:
            return await evaluate_version(conn, user["organization_id"], version_id)
        except MetricError as e:
            raise _bad(e)


@router.post("/preview")
async def preview_formula(body: PreviewIn, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        try:
            return await preview(conn, user["organization_id"], body.formula)
        except MetricError as e:
            raise _bad(e)
