"""Системный модуль: служебная информация о БД + статус первичной настройки."""
from fastapi import APIRouter, Depends

from ... import db
from ..auth.deps import require_roles

router = APIRouter(prefix="/system", tags=["system"])
setup_roles = require_roles("admin", "superadmin")


@router.get("/info")
async def info():
    """Сводка по БД: число таблиц и наличие ключевых объектов (для самодиагностики)."""
    async with db.get_pool().acquire() as conn:
        tables = await conn.fetchval(
            "select count(*) from information_schema.tables "
            "where table_schema='public' and table_type='BASE TABLE'"
        )
        has_access_fn = await conn.fetchval(
            "select exists(select 1 from pg_proc where proname='fn_resolve_access')"
        )
    return {"tables": tables, "fn_resolve_access": bool(has_access_fn)}


@router.get("/setup-status")
async def setup_status(user: dict = Depends(setup_roles)):
    """Готовность системы к работе (для мастера первичной настройки).
    Счётчики по организации + признак «свежая установка» (ничего не заведено).
    Доступно только admin/superadmin."""
    org = user["organization_id"]
    async with db.get_pool().acquire() as conn:
        c = await conn.fetchrow(
            "select "
            "(select count(*) from departments where organization_id=$1) as departments, "
            "(select count(*) from users where organization_id=$1) as users, "
            "(select count(*) from objects where organization_id=$1) as objects, "
            "(select count(*) from documents where organization_id=$1) as documents, "
            "(select count(distinct code) from dataset_releases where organization_id=$1 and status<>'superseded') as datasets, "
            "(select count(*) from dashboards where organization_id=$1) as dashboards",
            org,
        )
    d = {k: c[k] for k in ("departments", "users", "objects", "documents", "datasets", "dashboards")}
    # «Свежая установка»: нет отделов, объектов и дашбордов (пользователи — только
    # сид admin/superadmin). Тогда мастер показывается автоматически.
    d["fresh_install"] = (d["departments"] == 0 and d["objects"] == 0
                          and d["dashboards"] == 0 and d["users"] <= 2)
    return d
