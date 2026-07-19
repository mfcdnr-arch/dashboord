"""Сервис модуля «Пользователи»: отделы, роли, CRUD пользователей.

Управление — только admin (проверяется в роутере). Пользователи заводятся
с временным паролем и флагом must_change_password. Жёсткого удаления нет —
только блокировка (is_active), чтобы не терять историю/аудит.
"""
from __future__ import annotations

from typing import List, Optional

from ..auth.security import hash_password


class UsersError(Exception):
    """Ошибка бизнес-логики модуля пользователей (в роутере → 400/404)."""


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
async def list_users(conn, org_id) -> List[dict]:
    rows = await conn.fetch(
        "select u.id, u.login, u.full_name, u.last_name, u.first_name, u.middle_name, u.email, "
        "u.is_active, u.must_change_password, u.created_at, u.department_id, "
        "dep.name as department, "
        "coalesce((select array_agg(r.code order by r.code) from user_roles ur "
        "  join roles r on r.id=ur.role_id where ur.user_id=u.id), '{}') as roles "
        "from users u left join departments dep on dep.id=u.department_id "
        "where u.organization_id=$1 order by u.login", org_id)
    out = []
    for u in rows:
        out.append({
            "id": str(u["id"]), "login": u["login"], "full_name": u["full_name"],
            "last_name": u["last_name"], "first_name": u["first_name"], "middle_name": u["middle_name"],
            "email": u["email"], "is_active": u["is_active"], "must_change_password": u["must_change_password"],
            "department_id": str(u["department_id"]) if u["department_id"] else None,
            "department": u["department"], "roles": list(u["roles"]), "created_at": u["created_at"],
        })
    return out


async def _dept_ok(conn, org_id, department_id: Optional[str]) -> None:
    if department_id and not await conn.fetchval(
            "select 1 from departments where id=$1::uuid and organization_id=$2", department_id, org_id):
        raise UsersError("Отдел не найден")


async def _set_roles(conn, org_id, user_id: str, role_ids: List[str]) -> None:
    await conn.execute("delete from user_roles where user_id=$1::uuid", user_id)
    for rid in role_ids or []:
        if not await conn.fetchval("select 1 from roles where id=$1::uuid and organization_id=$2", rid, org_id):
            raise UsersError("Роль не найдена")
        await conn.execute(
            "insert into user_roles(user_id, role_id) values($1::uuid,$2::uuid) on conflict do nothing",
            user_id, rid)


async def create_user(conn, org_id, login: str, password: str, last_name, first_name, middle_name,
                      email, department_id, role_ids: List[str]) -> dict:
    login = (login or "").strip()
    if not login:
        raise UsersError("Укажите логин")
    if not password or len(password) < 4:
        raise UsersError("Пароль минимум 4 символа")
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
    await _set_roles(conn, org_id, uid, role_ids)
    return {"id": uid, "login": login}


async def _user_org(conn, org_id, user_id: str):
    return await conn.fetchrow(
        "select id, is_active from users where id=$1::uuid and organization_id=$2", user_id, org_id)


async def update_user(conn, org_id, user_id: str, last_name, first_name, middle_name,
                      email, department_id, role_ids: Optional[List[str]]) -> dict:
    if await _user_org(conn, org_id, user_id) is None:
        raise UsersError("Пользователь не найден")
    await _dept_ok(conn, org_id, department_id)
    full = _full_name(last_name, first_name, middle_name)
    await conn.execute(
        "update users set last_name=$2, first_name=$3, middle_name=$4, full_name=$5, "
        "email=$6, department_id=$7::uuid where id=$1::uuid",
        user_id, last_name, first_name, middle_name, full, email, department_id)
    if role_ids is not None:
        await _set_roles(conn, org_id, user_id, role_ids)
    return {"id": user_id}


async def set_active(conn, org_id, user_id: str, active: bool, actor_id: str) -> dict:
    if str(user_id) == str(actor_id):
        raise UsersError("Нельзя заблокировать самого себя")
    if await _user_org(conn, org_id, user_id) is None:
        raise UsersError("Пользователь не найден")
    await conn.execute("update users set is_active=$2 where id=$1::uuid", user_id, active)
    return {"id": user_id, "is_active": active}


async def reset_password(conn, org_id, user_id: str, new_password: str) -> dict:
    if not new_password or len(new_password) < 4:
        raise UsersError("Пароль минимум 4 символа")
    if await _user_org(conn, org_id, user_id) is None:
        raise UsersError("Пользователь не найден")
    await conn.execute(
        "update users set password_hash=$2, must_change_password=true where id=$1::uuid",
        user_id, hash_password(new_password))
    return {"id": user_id}
