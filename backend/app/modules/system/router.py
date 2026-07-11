"""Системный модуль: служебная информация о БД (пример модульного роутера)."""
from fastapi import APIRouter

from ... import db

router = APIRouter(prefix="/system", tags=["system"])


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
