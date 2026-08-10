"""Сервис модуля «Пользователи»: отделы, роли, CRUD пользователей.

Управление — только admin (проверяется в роутере). Пользователи заводятся
с временным паролем и флагом must_change_password. Жёсткого удаления нет —
только блокировка (is_active), чтобы не терять историю/аудит.
"""
from __future__ import annotations

from typing import List, Optional, Set

import asyncpg

from ..audit import service as audit_svc
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


def _login_filter(org_id, user_id, only_failed, start_idx: int = 1):
    """Условие и параметры выборки событий входа — общие для отчёта и выгрузки.

    Событие с `user_id is null` — это попытка входа под НЕСУЩЕСТВУЮЩИМ логином
    (организация неизвестна), поэтому в общем списке такие показываются, а при
    фильтре по конкретному пользователю — нет.
    """
    where = ["(e.organization_id=$%d or e.organization_id is null)" % start_idx]
    params = [org_id]
    if user_id:
        params.append(user_id)
        where.append("e.user_id=$%d::uuid" % (start_idx + len(params) - 1))
    if only_failed:
        where.append("not e.success")
    return " and ".join(where), params


async def login_events_report(conn, org_id, limit: int = 50, user_id: str | None = None,
                              only_failed: bool = False) -> dict:
    """Аудит входов: сводка по пользователям (входов/неудач/последний вход) +
    последние события (кто/когда/IP/успех).

    user_id — показать журнал по ОДНОМУ сотруднику: в организации с двумя
    десятками учёток общая лента не отвечает на вопрос «когда заходил Иванов».
    Сводка при этом остаётся полной — она и есть список для выбора.
    """
    summary = await conn.fetch(
        "select u.id, u.login, u.full_name, u.is_active, "
        "count(*) filter (where e.success) as logins, "
        "count(*) filter (where not e.success) as failed, "
        "max(e.created_at) filter (where e.success) as last_login "
        "from users u left join login_events e on e.user_id=u.id "
        "where u.organization_id=$1 group by u.id, u.login, u.full_name, u.is_active "
        "order by max(e.created_at) desc nulls last, u.login", org_id)
    where, params = _login_filter(org_id, user_id, only_failed)
    params.append(limit)
    recent = await conn.fetch(
        "select e.login, e.ip, e.user_agent, e.success, e.created_at, u.full_name "
        "from login_events e left join users u on u.id=e.user_id "
        f"where {where} order by e.created_at desc limit ${len(params)}", *params)
    return {
        "summary": [{
            "user_id": str(s["id"]), "login": s["login"], "full_name": s["full_name"],
            "is_active": s["is_active"],
            "logins": s["logins"], "failed": s["failed"], "last_login": s["last_login"],
        } for s in summary],
        "recent": [{
            "login": r["login"], "full_name": r["full_name"], "ip": r["ip"],
            "user_agent": r["user_agent"],
            "success": r["success"], "created_at": r["created_at"],
        } for r in recent],
        "filtered_by_user": user_id,
    }


async def login_events_export(conn, org_id, limit: int = 50000, user_id: str | None = None,
                              only_failed: bool = False):
    """Плоские строки журнала входов под выгрузку (CSV/XLSX): (headers, rows).

    Фильтры те же, что на экране: выгрузка должна совпадать с тем, что человек
    видит, иначе в файле окажется не то, что он отобрал.
    """
    where, params = _login_filter(org_id, user_id, only_failed)
    params.append(limit)
    rows = await conn.fetch(
        "select e.created_at, e.login, u.full_name, e.ip, e.user_agent, e.success "
        "from login_events e left join users u on u.id=e.user_id "
        f"where {where} order by e.created_at desc limit ${len(params)}", *params)
    headers = ["Дата/время", "Логин", "ФИО", "IP", "Устройство", "Результат"]
    out = [[
        r["created_at"].strftime("%Y-%m-%d %H:%M:%S") if r["created_at"] else "",
        r["login"], r["full_name"], r["ip"], r["user_agent"],
        "успех" if r["success"] else "неудача",
    ] for r in rows]
    return headers, out


async def user_activity(conn, org_id, user_id: str, limit: int = 100) -> dict:
    """«Кабинет сотрудника глазами администратора»: карточка (роли, отдел,
    состояние учётки, последний вход), входы, действия из аудита (включая
    просмотры дашбордов и выгрузки), комментарии и обращения — в одном месте
    вместо четырёх разных экранов.

    Это ПРОСМОТР, а не вход под чужой учётной записью: система принципиально
    не позволяет действовать от чужого имени, иначе аудит перестал бы отвечать
    на вопрос «кто это сделал».
    """
    target = await conn.fetchrow(
        "select u.id, u.login, u.full_name, u.email, u.is_active, u.created_at, "
        "       u.must_change_password, dep.name as department, "
        "       coalesce((select array_agg(r.name order by r.name) from user_roles ur "
        "         join roles r on r.id=ur.role_id where ur.user_id=u.id), '{}') as roles "
        "from users u left join departments dep on dep.id=u.department_id "
        "where u.id=$1::uuid and u.organization_id=$2", user_id, org_id)
    if target is None:
        raise UsersError("Пользователь не найден")
    logins = await conn.fetch(
        "select ip, user_agent, success, created_at from login_events "
        "where user_id=$1::uuid order by created_at desc limit $2", user_id, limit)
    login_count = await conn.fetchval(
        "select count(*) from login_events where user_id=$1::uuid and success", user_id)
    events = await audit_svc.list_events(conn, org_id, actor=user_id, include_views=True, limit=limit)
    comments = await conn.fetch(
        "select c.id, c.body, c.created_at, c.dashboard_id, d.name as dashboard_name "
        "from dashboard_comments c join dashboards d on d.id=c.dashboard_id "
        "where c.user_id=$1::uuid order by c.created_at desc limit $2", user_id, limit)
    # Обращения сотрудника — часть его «кабинета»: администратор видит, с чем
    # человек уже приходил, не переключаясь в раздел «Обращения».
    appeals = await conn.fetch(
        "select id, subject, status, created_at, updated_at, "
        "  (select count(*) from appeal_messages m where m.appeal_id = a.id) as messages "
        "from appeals a where user_id=$1::uuid and organization_id=$2 "
        "order by updated_at desc limit 20", user_id, org_id)
    last_login = await conn.fetchval(
        "select max(created_at) from login_events where user_id=$1::uuid and success", user_id)
    return {
        "user": {"id": str(target["id"]), "login": target["login"],
                "full_name": target["full_name"], "is_active": target["is_active"],
                "email": target["email"], "department": target["department"],
                "roles": list(target["roles"]), "created_at": target["created_at"],
                "must_change_password": target["must_change_password"],
                "last_login": last_login},
        "appeals": [{"id": str(a["id"]), "subject": a["subject"], "status": a["status"],
                    "messages": a["messages"], "created_at": a["created_at"],
                    "updated_at": a["updated_at"]} for a in appeals],
        "login_count": login_count,
        "logins": [{"ip": r["ip"], "user_agent": r["user_agent"], "success": r["success"],
                   "created_at": r["created_at"]} for r in logins],
        "events": events["items"],
        "comments": [{"id": str(r["id"]), "body": r["body"], "created_at": r["created_at"],
                     "dashboard_id": str(r["dashboard_id"]), "dashboard_name": r["dashboard_name"]}
                    for r in comments],
    }


async def reset_password(conn, org_id, user_id: str, new_password: str, actor: dict) -> dict:
    try:
        validate_password(new_password)
    except ValueError as e:
        raise UsersError(str(e))
    await _guard_manage(conn, org_id, user_id, actor)
    # password_changed_at отзывает ранее выданные токены этого пользователя
    # (миграция 033): сброс пароля админом = «выкинуть из всех сессий».
    await conn.execute(
        "update users set password_hash=$2, must_change_password=true, password_changed_at=date_trunc('second', now()) "
        "where id=$1::uuid",
        user_id, hash_password(new_password))
    return {"id": user_id}
