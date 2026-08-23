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

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ... import db
from ..auth.deps import get_current_user, require_roles
from .data_suggestions import suggest_from_data
from .describe import build_info_draft
from .parser import FormulaError, extract_dependencies
from .service import (
    MetricError,
    bulk_set_status,
    create_metric,
    create_version,
    current_values,
    delete_metric,
    evaluate_version,
    list_data_sources,
    pending_versions,
    preview,
    set_status,
    update_metric,
)
from .suggestions import suggest_derived_metrics
from .templates import TEMPLATES, build_formula, suggested_name

router = APIRouter(prefix="/metrics", tags=["metrics"])
manage = require_roles("superadmin", "admin", "moderator")
# Удаление показателя необратимо (версии формул уходят каскадом), поэтому
# доступно только владельцу системы — решение заказчика от 11.08.2026.
superadmin_only = require_roles("superadmin")


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
    """Доменная ошибка → код ответа. Отличаем «нет такого» (404) и «нельзя
    сейчас» — показатель в работе (409) — от ошибки ввода (400)."""
    msg = str(e)
    if "не найден" in msg:
        return HTTPException(status.HTTP_404_NOT_FOUND, msg)
    if "удаление отменено" in msg.lower():
        return HTTPException(status.HTTP_409_CONFLICT, msg)
    return HTTPException(status.HTTP_400_BAD_REQUEST, msg)


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
            # Ответственный за показатель (п. 11): по ТЗ он должен быть у
            # каждого KPI, а в интерфейсе поле не показывалось нигде — теперь
            # видно и кто это, и у каких показателей владельца нет.
            "m.owner_id, (select coalesce(nullif(u.full_name,''), u.login) from users u "
            " where u.id=m.owner_id) as owner_name, "
            "(select count(*) from metric_versions v where v.metric_id=m.id) as versions, "
            "(select mv.unit from metric_versions mv where mv.metric_id=m.id and mv.status='approved' "
            " order by mv.version_no desc limit 1) as unit, "
            "exists(select 1 from metric_versions v where v.metric_id=m.id and v.status='approved') as has_approved, "
            # Статус ЛУЧШЕЙ версии: одобрена → проверена → черновик. Без него список
            # печатал «черновик» и у метрики, которая уже проверена и ждёт одобрения
            # другим сотрудником — по списку было не понять, что от модератора ждут действия.
            "(select case when count(*) filter (where v.status='approved') > 0 then 'approved' "
            "             when count(*) filter (where v.status='validated') > 0 then 'validated' "
            "             when count(*) filter (where v.status='deprecated') > 0 "
            "                  and count(*) filter (where v.status='draft') = 0 then 'deprecated' "
            "             else 'draft' end "
            " from metric_versions v where v.metric_id=m.id) as best_status "
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


@router.get("/suggestions")
async def metric_suggestions(dashboard_id: str, user: dict = Depends(manage)):
    """Рекомендательная система, часть B: производные метрики (разница/доля/
    период-к-периоду/год-к-году/накопительный итог/план-факт/отклонение от
    цели) — область: метрики дашборда + метрики объекта, к которому дашборд
    привязан папкой. Определён ДО /{metric_id}, иначе тот перехватит путь."""
    async with db.get_pool().acquire() as conn:
        return await suggest_derived_metrics(conn, user["organization_id"], dashboard_id)


@router.get("/formula-templates")
async def formula_templates(user: dict = Depends(manage)):
    """Готовые рецепты метрик («Процент», «Выполнение плана», «Прирост к прошлому
    периоду» …) — чтобы завести показатель, не зная языка формул.
    Определён ДО /{metric_id}, иначе тот перехватит путь."""
    return {"items": TEMPLATES}


@router.post("/formula-templates/build")
async def build_template_formula(body: dict, user: dict = Depends(manage)):
    """Рецепт + выбранные столбцы → готовая формула DSL (сразу проверенная парсером)."""
    code = (body or {}).get("template_code")
    if not code:
        raise HTTPException(400, "Укажите template_code")
    try:
        formula = build_formula(code, (body or {}).get("values") or {})
    except FormulaError as e:
        raise HTTPException(400, str(e)) from None
    return {"formula": formula, "name": suggested_name(code, (body or {}).get("labels") or {})}


class BulkStatusIn(BaseModel):
    """Массовая проверка/одобрение. Правила те же, что у одиночной операции."""

    version_ids: List[str] = Field(min_length=1)
    target: str = "approved"   # validated | approved


@router.get("/pending")
async def metrics_pending(target: str = "approved", user: dict = Depends(manage)):
    """Что попадёт под массовую операцию — список ДО нажатия."""
    async with db.get_pool().acquire() as conn:
        return {"items": await pending_versions(conn, user["organization_id"], target)}


@router.post("/bulk-status")
async def metrics_bulk_status(body: BulkStatusIn, user: dict = Depends(manage)):
    """Проверить/одобрить несколько версий разом.

    Ограничения не ослаблены: свою версию по-прежнему нельзя одобрить (кроме
    суперадминистратора), черновик нельзя одобрить в обход проверки. Что не
    прошло — возвращается поимённо с причиной.
    """
    if body.target not in ("validated", "approved"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Допустимо: validated или approved")
    async with db.get_pool().acquire() as conn:
        roles = set(user.get("roles") or ())
        async with conn.transaction():
            return await bulk_set_status(
                conn, user["organization_id"], user["id"], body.version_ids, body.target, roles)


@router.get("/values")
async def metric_values(user: dict = Depends(get_current_user)):
    """Что показатели считают прямо сейчас — по лучшей версии формулы.

    Отдельным запросом, а не внутри списка: расчёт формул стоит заметно дороже
    выборки строк, а список нужен и там, где значения не нужны (пикеры KPI).
    Определён ДО /{metric_id}, иначе «values» уехало бы в него как id.
    """
    async with db.get_pool().acquire() as conn:
        return await current_values(conn, user["organization_id"])


@router.get("/data-suggestions")
async def data_suggestions(dataset_code: Optional[str] = None, object_id: Optional[str] = None,
                           user: dict = Depends(manage)):
    """Что можно посчитать по САМИМ ДАННЫМ: разбирает имена числовых столбцов
    датасета (план/факт, отправлено/доставлено, обращения/записались …) и
    предлагает готовые метрики. Определён ДО /{metric_id}."""
    async with db.get_pool().acquire() as conn:
        return await suggest_from_data(conn, user["organization_id"], dataset_code=dataset_code, object_id=object_id)


@router.get("/{metric_id}/info-draft")
async def metric_info_draft(metric_id: str, user: dict = Depends(manage)):
    """Черновик «расширенной информации о показателе»: что считает формула,
    откуда данные, как часто обновляются, как читать. Модератор правит и
    сохраняет — молча в БД ничего не пишется."""
    async with db.get_pool().acquire() as conn:
        m = await conn.fetchrow(
            "select id, code, name from metrics where id=$1::uuid and organization_id=$2",
            metric_id, user["organization_id"])
        if m is None:
            raise HTTPException(404, "Метрика не найдена")
        v = await conn.fetchrow(
            "select formula_expression, formula_ast, unit, status from metric_versions "
            "where metric_id=$1::uuid order by case status when 'approved' then 0 "
            "when 'validated' then 1 else 2 end, version_no desc limit 1", metric_id)
        if v is None:
            raise HTTPException(400, "У метрики нет ни одной версии формулы — сначала задайте формулу")

        ast = v["formula_ast"]
        if isinstance(ast, str):
            ast = json.loads(ast) if ast else None
        deps = extract_dependencies(ast) if ast else {"datasets": []}
        ds_codes = deps.get("datasets", [])

        # Человеческие имена столбцов и названия датасетов — чтобы в тексте не
        # осталось машинных кодов, которые пользователю ничего не говорят.
        names: dict = {}
        ds_titles: list = []
        periods, last_period = 0, None
        if ds_codes:
            rows = await conn.fetch(
                "select cf.code, cf.name from canonical_fields cf "
                "join objects o on o.id = cf.object_id where o.organization_id=$1", user["organization_id"])
            names = {r["code"]: r["name"] for r in rows}
            drows = await conn.fetch(
                "select code, max(name) as name, count(distinct reporting_period_start) as periods, "
                "       max(reporting_period_start) as last_period "
                "from dataset_releases where organization_id=$1 and code = any($2::text[]) "
                "and status<>'superseded' group by code", user["organization_id"], ds_codes)
            ds_titles = [r["name"] or r["code"] for r in drows]
            periods = max((r["periods"] or 0) for r in drows) if drows else 0
            lp = max((r["last_period"] for r in drows if r["last_period"]), default=None)
            last_period = lp.strftime("%d.%m.%Y") if lp else None

    return {"draft": build_info_draft(
        metric_name=m["name"], formula=v["formula_expression"], ast=ast, unit=v["unit"],
        status=v["status"], datasets=ds_titles, field_names=names,
        periods=periods, last_period=last_period)}


@router.get("/{metric_id}")
async def get_metric(metric_id: str, user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        m = await conn.fetchrow(
            "select m.id, m.code, m.name, m.description, m.info_text, m.created_at, m.owner_id, "
            "  (select coalesce(nullif(u.full_name,''), u.login) from users u where u.id=m.owner_id) as owner_name "
            "from metrics m where m.id=$1::uuid and m.organization_id=$2", metric_id, user["organization_id"]
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
            # «owner_id» в теле запроса, даже равный null, — это НАМЕРЕНИЕ
            # снять ответственного; отсутствие ключа — «не трогаем».
            return await update_metric(conn, user["organization_id"], metric_id,
                                       body.name, body.description, body.info_text, body.owner_id,
                                       owner_set="owner_id" in body.model_fields_set)
        except MetricError as e:
            raise _bad(e)


@router.delete("/{metric_id}")
async def remove_metric(metric_id: str, user: dict = Depends(superadmin_only)):
    async with db.get_pool().acquire() as conn:
        try:
            async with conn.transaction():
                return await delete_metric(conn, user["organization_id"], user["id"], metric_id)
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
                return await set_status(conn, user["organization_id"], user["id"], version_id, "approved",
                                        roles=set(user.get("roles") or ()))
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
