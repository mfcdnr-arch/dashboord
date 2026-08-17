"""Системный модуль: служебная информация о БД + статус первичной настройки +
графические настройки-пороги (взамен правки .env + рестарт)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ... import db
from ..auth.deps import require_roles
from . import logs_service as logs_svc
from . import settings_service as settings_svc

router = APIRouter(prefix="/system", tags=["system"])
setup_roles = require_roles("admin", "superadmin")


@router.get("/info")
async def info(user: dict = Depends(setup_roles)):
    """Сводка по БД: число таблиц и наличие ключевых объектов (для самодиагностики).

    Только admin/superadmin: эндпоинт раскрывает внутреннее устройство схемы
    (сколько таблиц, есть ли функция разрешения доступа) — постороннему это
    знать незачем. Раньше отвечал без токена (финальный аудит, сквозная проверка
    всех 160 операций на обязательность авторизации). Живость системы наружу
    отдаёт /health, он и остаётся публичным.
    """
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
    Счётчики по организации + признак «свежая установка» (структурно пусто) +
    серверный флаг «мастер закрыт». Доступно только admin/superadmin."""
    org = user["organization_id"]
    async with db.get_pool().acquire() as conn:
        c = await conn.fetchrow(
            "select "
            "(select count(*) from departments where organization_id=$1) as departments, "
            "(select count(*) from users where organization_id=$1) as users, "
            "(select count(*) from objects where organization_id=$1) as objects, "
            "(select count(*) from documents where organization_id=$1) as documents, "
            "(select count(distinct code) from dataset_releases where organization_id=$1 and status<>'superseded') as datasets, "
            "(select count(*) from dashboards where organization_id=$1) as dashboards, "
            "(select coalesce(setup_dismissed,false) from organizations where id=$1) as setup_dismissed",
            org,
        )
    d = {k: c[k] for k in ("departments", "users", "objects", "documents", "datasets", "dashboards")}
    d["setup_dismissed"] = bool(c["setup_dismissed"])
    # «Свежая установка» — по СТРУКТУРНОЙ пустоте (не зависит от числа юзеров/сида):
    # нет ни отделов, ни объектов, ни дашбордов. Мастер всплывает автоматически,
    # пока не закрыт (setup_dismissed). Оба условия проверяет фронт.
    d["fresh_install"] = (d["departments"] == 0 and d["objects"] == 0 and d["dashboards"] == 0)
    return d


@router.post("/setup-dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def setup_dismiss(user: dict = Depends(setup_roles)):
    """Отметить первичную настройку завершённой/пропущенной (серверный флаг —
    не всплывает при смене браузера). admin/superadmin."""
    async with db.get_pool().acquire() as conn:
        await conn.execute(
            "update organizations set setup_dismissed=true where id=$1", user["organization_id"])


class SystemSettingsIn(BaseModel):
    login_max_attempts: Optional[int] = Field(None, ge=0, le=100)
    login_lockout_minutes: Optional[int] = Field(None, ge=1, le=1440)
    cpu_warn: Optional[float] = Field(None, gt=0, lt=100)
    cpu_crit: Optional[float] = Field(None, gt=0, le=100)
    ram_warn: Optional[float] = Field(None, gt=0, lt=100)
    ram_crit: Optional[float] = Field(None, gt=0, le=100)
    disk_warn: Optional[float] = Field(None, gt=0, lt=100)
    disk_crit: Optional[float] = Field(None, gt=0, le=100)


class OrgSettingsIn(BaseModel):
    stale_days: Optional[int] = Field(None, ge=1, le=3650)
    retention_months: Optional[int] = Field(None, ge=0, le=120)
    appeal_response_hours: Optional[int] = Field(None, ge=1, le=720)


@router.get("/settings")
async def get_settings(user: dict = Depends(setup_roles)):
    """Эффективные пороги (системные + организации), для страницы «Настройки».
    admin/superadmin."""
    async with db.get_pool().acquire() as conn:
        return {
            "system": await settings_svc.get_system_settings(conn),
            "org": await settings_svc.get_org_settings(conn, user["organization_id"]),
        }


@router.put("/settings/system")
async def put_system_settings(body: SystemSettingsIn, user: dict = Depends(setup_roles)):
    """Обновить системные пороги (вход/блокировка, CPU/RAM/диск). admin/superadmin."""
    async with db.acquire(user["id"]) as conn:
        async with conn.transaction():
            try:
                return await settings_svc.update_system_settings(
                    conn, user["id"], body.model_dump(exclude_none=True))
            except settings_svc.SettingsError as e:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))


@router.put("/settings/org")
async def put_org_settings(body: OrgSettingsIn, user: dict = Depends(setup_roles)):
    """Обновить пороги организации (свежесть данных, ретенция). admin/superadmin."""
    async with db.acquire(user["id"]) as conn:
        async with conn.transaction():
            return await settings_svc.update_org_settings(
                conn, user["organization_id"], body.model_dump(exclude_none=True))


@router.get("/logs")
async def get_logs(
    service: str,
    minutes: int = Query(30, ge=1, le=1440),
    limit: int = Query(200, ge=1, le=1000),
    q: Optional[str] = Query(None, max_length=200),
    user: dict = Depends(setup_roles),
):
    """Просмотр логов сервиса за окно (через Loki — уже есть в мониторинг-стеке).
    admin/superadmin. Если Loki недоступен — понятная подсказка, не 500."""
    try:
        lines = await logs_svc.query_logs(service, minutes, limit, q)
        return {"available": True, "services": list(logs_svc.KNOWN_SERVICES), "lines": lines}
    except logs_svc.LogsUnavailable:
        return {
            "available": False, "services": list(logs_svc.KNOWN_SERVICES), "lines": [],
            "hint": "Логи недоступны — мониторинг (Loki), похоже, не включён. "
                    "Запустите docker-compose.monitoring.yml или install.sh --monitoring.",
        }
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
