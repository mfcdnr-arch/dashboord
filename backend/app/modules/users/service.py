"""Сервис модуля «Пользователи»: отделы, роли, CRUD пользователей.

Управление — только admin (проверяется в роутере). Пользователи заводятся
с временным паролем и флагом must_change_password. Жёсткого удаления нет —
только блокировка (is_active), чтобы не терять историю/аудит.
"""
from __future__ import annotations

from typing import List, Optional, Set

import asyncpg

from ..auth.security import hash_password, validate_password


class UsersError(Exception):
    """Ошибка бизнес-логики модуля пользователей (в роутере → 400/404)."""


class UsersForbidden(UsersError):
    """Недостаточно прав по иерархии ролей (в роутере → 403)."""


# --------------------------------------------------------------------------- #
# Иерархия ролей управления пользователями
#   superadmin (100) > admin (50) > остальные (0)
# Правила: суперадмина может трогать только суперадмин; роль superadmin может
# выдавать/снимать только суперадмин; нельзя оставить систему без активного
# суперадмина («защита последнего»).
# --------------------------------------------------------------------------- #
SUPERADMIN = "superadmin"
ADMIN = "admin"
_ROLE_RANK = {SUPERADMIN: 100, ADMIN: 50}


def _rank(roles) -> int:
    return max((_ROLE_RANK.get(r, 0) for r in roles), default=0)


def _can_manage(actor_roles: Set[str], target_roles: Set[str]) -> bool:
    """Может ли актор (admin/superadmin) управлять целевым пользователем."""
    if SUPERADMIN in target_roles:
        return SUPERADMIN in actor_roles   # суперадмина — только суперадмин
    return True                             # остальных — и admin, и superadmin


async def _roles_of(conn, user_id: str) -> Set[str]:
    rows = await conn.fetch(
        "select r.code from user_roles ur join roles r on r.id=ur.role_id where ur.user_id=$1::uuid", user_id)
    return {r["code"] for r in rows}


async def _active_superadmin_count(conn, org_id) -> int:
    return await conn.fetchval(
        "select count(*) from users u join user_roles ur on ur.user_id=u.id "
        "join roles r on r.id=ur.role_id "
        "where u.organization_id=$1 and r.code=$2 and u.is_active", org_id, SUPERADMIN) or 0


async def _guard_manage(conn, org_id, user_id: str, actor: dict) -> Set[str]:
    """Проверяет право актора управлять пользователем; возвращает роли цели."""
    if await _user_org(conn, org_id, user_id) is None:
        raise UsersError("Пользователь не найден")
    troles = await _roles_of(conn, user_id)
    if not _can_manage(set(actor.get("roles") or []), troles):
        raise UsersForbidden("Управлять суперадминистратором может только суперадминистратор")
    return troles


async def _guard_last_superadmin(conn, org_id, user_id: str, target_roles: Set[str]) -> None:
    """Не даёт оставить систему без активного суперадмина (блок/удаление/снятие роли)."""
    if SUPERADMIN not in target_roles:
        return
    active = await _active_superadmin_count(conn, org_id)
    target_active = await conn.fetchval("select is_active from users where id=$1::uuid", user_id)
    if active - (1 if target_active else 0) < 1:
        raise UsersError("Нельзя оставить систему без активного суперадминистратора")


def _full_name(last: Optional[str], first: Optional[str], middle: Optional[str]) -> Optional[str]:
    parts = [p.strip() for p in (last, first, middle) if p and p.strip()]
    return " ".join(parts) or None


# --------------------------------------------------------------------------- #
# Отделы (справочник)
# --------------------------------------------------------------------------- #
async def list_departments(conn, org_id) -> List[dict]:
    rows = await conn.fetch(
        "select d.id, d.name, "
        "(select count(*) from users u where u.department_id=d.id) as users "
        "from departments d where d.organization_id=$1 order by d.name", org_id)
    return [{"id": str(r["id"]), "name": r["name"], "users": r["users"]} for r in rows]


async def create_department(conn, org_id, name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise UsersError("Укажите название отдела")
    if await conn.fetchval("select 1 from departments where organization_id=$1 and name=$2", org_id, name):
        raise UsersError("Отдел с таким названием уже есть")
    row = await conn.fetchrow(
        "insert into departments(organization_id, name) values($1,$2) returning id, name", org_id, name)
    return {"id": str(row["id"]), "name": row["name"]}


async def delete_department(conn, org_id, department_id: str) -> None:
    res = await conn.execute(
        "delete from departments where id=$1::uuid and organization_id=$2", department_id, org_id)
    if res.endswith("0"):
        raise UsersError("Отдел не найден")


# --------------------------------------------------------------------------- #
# Роли (для выбора при заведении пользователя)
# --------------------------------------------------------------------------- #
async def list_roles(conn, org_id) -> List[dict]:
    rows = await conn.fetch(
        "select id, code, name from roles where organization_id=$1 order by name", org_id)
    return [{"id": str(r["id"]), "code": r["code"], "name": r["name"]} for r in rows]


# --------------------------------------------------------------------------- #
# Пользователи
# --------------------------------------------------------------------------- #
async def list_users(conn, org_id, q: Optional[str] = None, limit: int = 50, offset: int = 0) -> dict:
    """Постранично: {total, limit, offset, items}. q — поиск по логину/ФИО (ilike)."""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    where = "u.organization_id=$1"
    params: list = [org_id]
    if q and q.strip():
        params.append(f"%{q.strip()}%")
        where += f" and (u.login ilike ${len(params)} or u.full_name ilike ${len(params)})"
    total = await conn.fetchval(f"select count(*) from users u where {where}", *params)
    rows = await conn.fetch(
        "select u.id, u.login, u.full_name, u.last_name, u.first_name, u.middle_name, u.email, "
        "u.is_active, u.must_change_password, u.created_at, u.department_id, "
        "dep.name as department, "
        "coalesce((select array_agg(r.code order by r.code) from user_roles ur "
        "  join roles r on r.id=ur.role_id where ur.user_id=u.id), '{}') as roles "
        "from users u left join departments dep on dep.id=u.department_id "
        f"where {where} order by u.login limit ${len(params) + 1} offset ${len(params) + 2}",
        *params, limit, offset)
    items = []
    for u in rows:
        items.append({
            "id": str(u["id"]), "login": u["login"], "full_name": u["full_name"],
            "last_name": u["last_name"], "first_name": u["first_name"], "middle_name": u["middle_name"],
            "email": u["email"], "is_active": u["is_active"], "must_change_password": u["must_change_password"],
            "department_id": str(u["department_id"]) if u["department_id"] else None,
            "department": u["department"], "roles": list(u["roles"]), "created_at": u["created_at"],
        })
    return {"total": total, "limit": limit, "offset": offset, "items": items}


async def _dept_ok(conn, org_id, department_id: Optional[str]) -> None:
    if department_id and not await conn.fetchval(
            "select 1 from departments where id=$1::uuid and organization_id=$2", department_id, org_id):
        raise UsersError("Отдел не найден")


async def _set_roles(conn, org_id, user_id: str, role_ids: List[str],
                     actor: dict, current_roles: Set[str]) -> None:
    # Коды запрошенных ролей (заодно валидируем принадлежность организации).
    new_codes: Set[str] = set()
    for rid in role_ids or []:
        code = await conn.fetchval(
            "select code from roles where id=$1::uuid and organization_id=$2", rid, org_id)
        if code is None:
            raise UsersError("Роль не найдена")
        new_codes.add(code)
    actor_roles = set(actor.get("roles") or [])
    # Эскалация: выдавать/снимать роль superadmin может только superadmin.
    touches_superadmin = SUPERADMIN in new_codes or SUPERADMIN in current_roles
    if touches_superadmin and SUPERADMIN not in actor_roles:
        raise UsersForbidden("Роль «Суперадминистратор» может назначать только суперадминистратор")
    # Защита последнего: нельзя снять superadmin с последнего активного.
    if SUPERADMIN in current_roles and SUPERADMIN not in new_codes:
        await _guard_last_superadmin(conn, org_id, user_id, current_roles)
    # Суперадмин — надмножество admin: при выдаче superadmin автоматически
    # добавляем и admin (иначе «чистый суперадмин» не имел бы обычного доступа).
    final_ids = list(role_ids or [])
    if SUPERADMIN in new_codes and ADMIN not in new_codes:
        admin_rid = await conn.fetchval(
            "select id from roles where organization_id=$1 and code=$2", org_id, ADMIN)
        if admin_rid is not None and str(admin_rid) not in {str(x) for x in final_ids}:
            final_ids.append(admin_rid)
    await conn.execute("delete from user_roles where user_id=$1::uuid", user_id)
    for rid in final_ids:
        await conn.execute(
            "insert into user_roles(user_id, role_id) values($1::uuid,$2::uuid) on conflict do nothing",
            user_id, rid)


async def create_user(conn, org_id, login: str, password: str, last_name, first_name, middle_name,
                      email, department_id, role_ids: List[str], actor: dict) -> dict:
    login = (login or "").strip()
    if not login:
        raise UsersError("Укажите логин")
    try:
        validate_password(password, login)
    except ValueError as e:
        raise UsersError(str(e))
    if await conn.fetchval("select 1 from users where organization_id=$1 and login=$2", org_id, login):
        raise UsersError("Пользователь с таким логином уже есть")
    await _dept_ok(conn, org_id, department_id)
    full = _full_name(last_name, first_name, middle_name)
    row = await conn.fetchrow(
        "insert into users(organization_id, login, password_hash, full_name, last_name, first_name, "
        "middle_name, email, department_id, must_change_password, is_active) "
        "values($1,$2,$3,$4,$5,$6,$7,$8,$9::uuid,true,true) returning id",
        org_id, login, hash_password(password), full, last_name, first_name, middle_name, email, department_id)
    uid = str(row["id"])
    await _set_roles(conn, org_id, uid, role_ids, actor, current_roles=set())
    return {"id": uid, "login": login}


async def _user_org(conn, org_id, user_id: str):
    return await conn.fetchrow(
        "select id, is_active from users where id=$1::uuid and organization_id=$2", user_id, org_id)


async def update_user(conn, org_id, user_id: str, last_name, first_name, middle_name,
                      email, department_id, role_ids: Optional[List[str]], actor: dict) -> dict:
    troles = await _guard_manage(conn, org_id, user_id, actor)
    await _dept_ok(conn, org_id, department_id)
    full = _full_name(last_name, first_name, middle_name)
    await conn.execute(
        "update users set last_name=$2, first_name=$3, middle_name=$4, full_name=$5, "
        "email=$6, department_id=$7::uuid where id=$1::uuid",
        user_id, last_name, first_name, middle_name, full, email, department_id)
    if role_ids is not None:
        await _set_roles(conn, org_id, user_id, role_ids, actor, current_roles=troles)
    return {"id": user_id}


async def set_active(conn, org_id, user_id: str, active: bool, actor: dict) -> dict:
    if str(user_id) == str(actor["id"]):
        raise UsersError("Нельзя заблокировать самого себя")
    troles = await _guard_manage(conn, org_id, user_id, actor)
    if not active:  # блокировка суперадмина — беречь последнего
        await _guard_last_superadmin(conn, org_id, user_id, troles)
    await conn.execute("update users set is_active=$2 where id=$1::uuid", user_id, active)
    return {"id": user_id, "is_active": active}


async def delete_user(conn, org_id, user_id: str, actor: dict) -> dict:
    """Гибридное удаление: жёстко удаляет только «чистого» пользователя (без
    созданных объектов/истории). Если есть связанные данные (FK) — отказ с
    подсказкой использовать блокировку, чтобы не терять историю/аудит."""
    if str(user_id) == str(actor["id"]):
        raise UsersError("Нельзя удалить самого себя")
    troles = await _guard_manage(conn, org_id, user_id, actor)
    await _guard_last_superadmin(conn, org_id, user_id, troles)
    # user_roles/сессии/получатели уведомлений уходят по ON DELETE CASCADE;
    # login_events/комментарии/actor аудита — по ON DELETE SET NULL. Остальные
    # ссылки (created_by/uploaded_by/…) с RESTRICT — заблокируют удаление.
    try:
        async with conn.transaction():
            res = await conn.execute("delete from users where id=$1::uuid and organization_id=$2", user_id, org_id)
    except asyncpg.ForeignKeyViolationError:
        raise UsersError("У пользователя есть созданные объекты или история действий — "
                         "жёсткое удаление невозможно. Заблокируйте пользователя (сохранит аудит).")
    if res.endswith("0"):
        raise UsersError("Пользователь не найден")
    return {"id": user_id, "deleted": True}


async def login_events_report(conn, org_id, limit: int = 50) -> dict:
    """Аудит входов: сводка по пользователям (входов/неудач/последний вход) +
    последние события (кто/когда/IP/успех)."""
    summary = await conn.fetch(
        "select u.login, u.full_name, u.is_active, "
        "count(*) filter (where e.success) as logins, "
        "count(*) filter (where not e.success) as failed, "
        "max(e.created_at) filter (where e.success) as last_login "
        "from users u left join login_events e on e.user_id=u.id "
        "where u.organization_id=$1 group by u.id, u.login, u.full_name, u.is_active "
        "order by max(e.created_at) desc nulls last, u.login", org_id)
    recent = await conn.fetch(
        "select e.login, e.ip, e.success, e.created_at, u.full_name "
        "from login_events e left join users u on u.id=e.user_id "
        "where e.organization_id=$1 or e.organization_id is null "
        "order by e.created_at desc limit $2", org_id, limit)
    return {
        "summary": [{
            "login": s["login"], "full_name": s["full_name"], "is_active": s["is_active"],
            "logins": s["logins"], "failed": s["failed"], "last_login": s["last_login"],
        } for s in summary],
        "recent": [{
            "login": r["login"], "full_name": r["full_name"], "ip": r["ip"],
            "success": r["success"], "created_at": r["created_at"],
        } for r in recent],
    }


async def login_events_export(conn, org_id, limit: int = 50000):
    """Плоские строки журнала входов под выгрузку (CSV/XLSX): (headers, rows).
    Все события (успех и неудача), новые сверху."""
    rows = await conn.fetch(
        "select e.created_at, e.login, u.full_name, e.ip, e.user_agent, e.success "
        "from login_events e left join users u on u.id=e.user_id "
        "where e.organization_id=$1 or e.organization_id is null "
        "order by e.created_at desc limit $2", org_id, limit)
    headers = ["Дата/время", "Логин", "ФИО", "IP", "Устройство", "Результат"]
    out = [[
        r["created_at"].strftime("%Y-%m-%d %H:%M:%S") if r["created_at"] else "",
        r["login"], r["full_name"], r["ip"], r["user_agent"],
        "успех" if r["success"] else "неудача",
    ] for r in rows]
    return headers, out


async def reset_password(conn, org_id, user_id: str, new_password: str, actor: dict) -> dict:
    try:
        validate_password(new_password)
    except ValueError as e:
        raise UsersError(str(e))
    await _guard_manage(conn, org_id, user_id, actor)
    await conn.execute(
        "update users set password_hash=$2, must_change_password=true where id=$1::uuid",
        user_id, hash_password(new_password))
    return {"id": user_id}
