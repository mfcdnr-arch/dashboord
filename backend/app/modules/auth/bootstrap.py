"""Первичная инициализация: организация по умолчанию, системные роли, admin.

Идемпотентно: выполняется при старте приложения, ничего не ломает при повторе.
"""
from __future__ import annotations

from ... import db
from ...config import settings
from .security import hash_password

# code, name, can_edit_formulas, can_moderate
SYSTEM_ROLES = [
    ("superadmin", "Суперадминистратор", True, True),
    ("admin", "Администратор", True, True),
    ("moderator", "Модератор", True, True),
    ("senior_moderator", "Старший модератор", True, True),
    ("author", "Автор", False, False),
    ("publisher", "Публикатор", False, False),
    ("analyst", "Аналитик", False, False),
    ("user", "Пользователь", False, False),
]


async def ensure_seed() -> None:
    async with db.get_pool().acquire() as conn:
        org_id = await conn.fetchval(
            "select id from organizations where code='default'"
        )
        if org_id is None:
            org_id = await conn.fetchval(
                "insert into organizations(name, code) values('По умолчанию','default') returning id"
            )

        for code, name, can_formulas, can_moderate in SYSTEM_ROLES:
            await conn.execute(
                "insert into roles(organization_id, code, name, is_system, can_edit_formulas, can_moderate) "
                "values($1,$2,$3,true,$4,$5) on conflict (organization_id, code) do nothing",
                org_id, code, name, can_formulas, can_moderate,
            )

        await _ensure_account(conn, org_id, settings.admin_login,
                              settings.admin_password, "Администратор", ["admin"])
        # Учётка владельца-суперадмина. Роли аддитивны: даём superadmin (права над
        # ЛЮБЫМ пользователем, включая admin) И admin (обычный доступ ко всем
        # разделам без правки всех require_roles). Пароль временный — смена
        # обязательна при 1-м входе. В проде задать SUPERADMIN_PASSWORD в .env.prod.
        await _ensure_account(conn, org_id, settings.superadmin_login,
                              settings.superadmin_password, "Суперадминистратор", ["superadmin", "admin"])


async def _ensure_account(conn, org_id, login: str, password: str, full_name: str, role_codes: list) -> None:
    """Идемпотентно создаёт пользователя с указанными ролями и временным паролем."""
    uid = await conn.fetchval(
        "select id from users where organization_id=$1 and login=$2", org_id, login)
    if uid is None:
        uid = await conn.fetchval(
            "insert into users(organization_id, login, password_hash, full_name, must_change_password) "
            "values($1,$2,$3,$4,true) returning id",
            org_id, login, hash_password(password), full_name,
        )
    for code in role_codes:
        role_id = await conn.fetchval(
            "select id from roles where organization_id=$1 and code=$2", org_id, code)
        if role_id is not None:
            await conn.execute(
                "insert into user_roles(user_id, role_id) values($1,$2) on conflict do nothing",
                uid, role_id,
            )
