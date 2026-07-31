"""Графическое управление порогами (взамен правки .env + рестарт).

Системные пороги (один сервер на инсталляцию — не org-scoped): вход/блокировка,
CPU/RAM/диск warn/crit для /reports/system. Хранятся в синглтон-таблице
system_settings (ровно одна строка, id=1).

Org-scoped пороги (свежесть/ретенция — уже считаются по организации в
maintenance.service): хранятся в organizations.settings (jsonb).

Оба вида — с fallback на .env (config.py), если строка/ключ отсутствует —
чтобы существующие переменные окружения оставались рабочим дефолтом.
"""
from __future__ import annotations

import json

from ...config import settings as env_settings

SYSTEM_KEYS = (
    "login_max_attempts", "login_lockout_minutes",
    "cpu_warn", "cpu_crit", "ram_warn", "ram_crit", "disk_warn", "disk_crit",
)
SYSTEM_DEFAULTS = {
    "login_max_attempts": env_settings.login_max_attempts,
    "login_lockout_minutes": env_settings.login_lockout_minutes,
    "cpu_warn": 70.0, "cpu_crit": 90.0,
    "ram_warn": 80.0, "ram_crit": 92.0,
    "disk_warn": 80.0, "disk_crit": 92.0,
}
ORG_KEYS = ("stale_days", "retention_months")
ORG_DEFAULTS = {
    "stale_days": env_settings.stale_days,
    "retention_months": env_settings.retention_months,
}

_PAIRS = (("cpu_warn", "cpu_crit"), ("ram_warn", "ram_crit"), ("disk_warn", "disk_crit"))


class SettingsError(Exception):
    """Доменная ошибка модуля настроек (нарушен диапазон/порядок warn<crit)."""


async def get_system_settings(conn) -> dict:
    row = await conn.fetchrow("select * from system_settings where id=1")
    if not row:
        return dict(SYSTEM_DEFAULTS)
    return {k: row[k] for k in SYSTEM_KEYS}


async def update_system_settings(conn, user_id, patch: dict) -> dict:
    current = await get_system_settings(conn)
    current.update({k: v for k, v in patch.items() if v is not None})
    _validate_pairs(current)
    set_clause = ", ".join(f"{k}=${i + 1}" for i, k in enumerate(SYSTEM_KEYS))
    await conn.execute(
        f"update system_settings set {set_clause}, updated_at=now(), updated_by=${len(SYSTEM_KEYS) + 1} where id=1",
        *[current[k] for k in SYSTEM_KEYS], user_id)
    return current


async def get_org_settings(conn, org_id) -> dict:
    raw = await conn.fetchval("select settings from organizations where id=$1", org_id)
    data = json.loads(raw) if raw else {}
    return {**ORG_DEFAULTS, **{k: data[k] for k in ORG_KEYS if k in data}}


async def update_org_settings(conn, org_id, patch: dict) -> dict:
    current = await get_org_settings(conn, org_id)
    current.update({k: v for k, v in patch.items() if v is not None})
    await conn.execute(
        "update organizations set settings = settings || $2::jsonb where id=$1",
        org_id, json.dumps({k: current[k] for k in ORG_KEYS}))
    return current


def _validate_pairs(current: dict) -> None:
    for warn_key, crit_key in _PAIRS:
        if current[warn_key] >= current[crit_key]:
            raise SettingsError(f"{warn_key} должен быть меньше {crit_key}")
