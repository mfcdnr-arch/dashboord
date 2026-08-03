"""Обращения пользователей к администратору/модератору (волна C).

Лёгкий тред: appeals (заявка, статус open→answered→closed) + appeal_messages
(сообщения обеих сторон). Один и тот же эндпоинт «добавить сообщение»
обслуживает и пользователя, и staff — роль определяется на лету по БД (роли
не всегда есть в user-словаре зависимости get_current_user).

Создание доступно и НЕАВТОРИЗОВАННО (create_appeal_by_login) — для
заблокированного аккаунта, который не может войти и получить обычный JWT.
"""
from __future__ import annotations

from typing import Optional

from ..audit import service as audit_svc
from ..notifications import service as notif_svc

MAX_BODY = 4000
MAX_SUBJECT = 200
STAFF_ROLES = {"admin", "moderator", "senior_moderator", "superadmin"}


class AppealsError(Exception):
    """Доменная ошибка модуля обращений."""


async def _is_staff(conn, user_id) -> bool:
    rows = await conn.fetch(
        "select r.code from user_roles ur join roles r on r.id=ur.role_id where ur.user_id=$1", user_id)
    return bool({r["code"] for r in rows} & STAFF_ROLES)


def _clip(text: Optional[str], limit: int) -> Optional[str]:
    text = (text or "").strip()
    return text[:limit] if text else None


async def create_appeal(conn, org_id, user: dict, subject: Optional[str], body: str) -> dict:
    body = (body or "").strip()
    if not body:
        raise AppealsError("Пустое сообщение")
    if len(body) > MAX_BODY:
        raise AppealsError(f"Слишком длинное сообщение (максимум {MAX_BODY} символов)")
    subject = _clip(subject, MAX_SUBJECT)
    row = await conn.fetchrow(
        "insert into appeals(organization_id, user_id, subject) values($1,$2,$3) returning id, created_at",
        org_id, user["id"], subject)
    await conn.execute(
        "insert into appeal_messages(appeal_id, sender_user_id, is_staff, body) values($1,$2,false,$3)",
        row["id"], user["id"], body)
    mgmt = [u for u in await notif_svc.management_user_ids(conn, org_id) if str(u) != str(user["id"])]
    if mgmt:
        await notif_svc.notify(
            conn, org_id, "appeal.created", "appeal", str(row["id"]),
            {"author": user.get("full_name") or user.get("login"), "subject": subject, "snippet": body[:140]},
            mgmt)
    return {"id": str(row["id"]), "created_at": row["created_at"]}


async def create_appeal_by_login(conn, login: str, body: str) -> None:
    """Заблокированный аккаунт: без JWT. Молчаливо ничего не делает, если логин
    не найден — ответ API одинаков в любом случае (не подтверждаем существование
    учётки посторонним)."""
    body = (body or "").strip()
    if not body:
        return
    body = body[:MAX_BODY]
    row = await conn.fetchrow(
        "select id, organization_id, full_name from users where login=$1", login)
    if row is None:
        return
    ap = await conn.fetchrow(
        "insert into appeals(organization_id, user_id, subject) values($1,$2,'Аккаунт заблокирован') returning id",
        row["organization_id"], row["id"])
    await conn.execute(
        "insert into appeal_messages(appeal_id, sender_user_id, is_staff, body) values($1,$2,false,$3)",
        ap["id"], row["id"], body)
    mgmt = await notif_svc.management_user_ids(conn, row["organization_id"])
    if mgmt:
        await notif_svc.notify(
            conn, row["organization_id"], "appeal.created", "appeal", str(ap["id"]),
            {"author": row["full_name"] or login, "subject": "Аккаунт заблокирован", "snippet": body[:140]},
            mgmt)


def _row_to_summary(r) -> dict:
    return {
        "id": str(r["id"]),
        "subject": r["subject"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "last_message": r["last_body"],
        "last_is_staff": r["last_is_staff"],
        "author": r["author"] if "author" in r.keys() else None,
    }


async def list_mine(conn, user_id, limit: int = 50, offset: int = 0) -> dict:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    total = await conn.fetchval("select count(*) from appeals where user_id=$1", user_id)
    rows = await conn.fetch(
        "select a.id, a.subject, a.status, a.created_at, a.updated_at, "
        "(select body from appeal_messages m where m.appeal_id=a.id order by m.created_at desc limit 1) as last_body, "
        "(select is_staff from appeal_messages m where m.appeal_id=a.id order by m.created_at desc limit 1) as last_is_staff "
        "from appeals a where a.user_id=$1 order by a.updated_at desc limit $2 offset $3",
        user_id, limit, offset)
    return {"total": total, "limit": limit, "offset": offset, "items": [_row_to_summary(r) for r in rows]}


async def list_org(conn, org_id, status_filter: Optional[str], limit: int = 50, offset: int = 0) -> dict:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    where = "a.organization_id=$1"
    args: list = [org_id]
    if status_filter:
        args.append(status_filter)
        where += f" and a.status=${len(args)}"
    total = await conn.fetchval(f"select count(*) from appeals a where {where}", *args)
    args_paged = args + [limit, offset]
    rows = await conn.fetch(
        f"select a.id, a.subject, a.status, a.created_at, a.updated_at, "
        "coalesce(u.full_name, u.login) as author, "
        "(select body from appeal_messages m where m.appeal_id=a.id order by m.created_at desc limit 1) as last_body, "
        "(select is_staff from appeal_messages m where m.appeal_id=a.id order by m.created_at desc limit 1) as last_is_staff "
        f"from appeals a join users u on u.id=a.user_id where {where} "
        f"order by a.updated_at desc limit ${len(args) + 1} offset ${len(args) + 2}",
        *args_paged)
    return {"total": total, "limit": limit, "offset": offset, "items": [_row_to_summary(r) for r in rows]}


async def open_count(conn, org_id) -> dict:
    n = await conn.fetchval("select count(*) from appeals where organization_id=$1 and status='open'", org_id)
    return {"open": n}


async def get_appeal(conn, org_id, user: dict, appeal_id: str) -> dict:
    ap = await conn.fetchrow(
        "select a.id, a.subject, a.status, a.created_at, a.updated_at, a.user_id, "
        "coalesce(u.full_name, u.login) as author "
        "from appeals a join users u on u.id=a.user_id "
        "where a.id=$1::uuid and a.organization_id=$2", appeal_id, org_id)
    if ap is None:
        raise AppealsError("Обращение не найдено")
    if str(ap["user_id"]) != str(user["id"]) and not await _is_staff(conn, user["id"]):
        raise AppealsError("Обращение не найдено")
    msgs = await conn.fetch(
        "select m.id, m.is_staff, m.body, m.created_at, coalesce(u.full_name, u.login, '— (удалён)') as author "
        "from appeal_messages m left join users u on u.id=m.sender_user_id "
        "where m.appeal_id=$1::uuid order by m.created_at", appeal_id)
    return {
        "id": str(ap["id"]), "subject": ap["subject"], "status": ap["status"],
        "created_at": ap["created_at"], "updated_at": ap["updated_at"], "author": ap["author"],
        "messages": [{"id": str(m["id"]), "is_staff": m["is_staff"], "body": m["body"],
                     "created_at": m["created_at"], "author": m["author"]} for m in msgs],
    }


async def add_message(conn, org_id, user: dict, appeal_id: str, body: str) -> dict:
    ap = await conn.fetchrow(
        "select id, user_id, status from appeals where id=$1::uuid and organization_id=$2", appeal_id, org_id)
    if ap is None:
        raise AppealsError("Обращение не найдено")
    is_staff = await _is_staff(conn, user["id"])
    if str(ap["user_id"]) != str(user["id"]) and not is_staff:
        raise AppealsError("Обращение не найдено")
    body = (body or "").strip()
    if not body:
        raise AppealsError("Пустое сообщение")
    if len(body) > MAX_BODY:
        raise AppealsError(f"Слишком длинное сообщение (максимум {MAX_BODY} символов)")
    row = await conn.fetchrow(
        "insert into appeal_messages(appeal_id, sender_user_id, is_staff, body) values($1::uuid,$2,$3,$4) "
        "returning id, created_at", appeal_id, user["id"], is_staff, body)
    new_status = "answered" if is_staff else "open"
    await conn.execute("update appeals set status=$2, updated_at=now() where id=$1::uuid", appeal_id, new_status)
    if is_staff:
        if str(ap["user_id"]) != str(user["id"]):
            await notif_svc.notify(
                conn, org_id, "appeal.replied", "appeal", appeal_id,
                {"author": user.get("full_name") or user.get("login"), "snippet": body[:140]}, [ap["user_id"]])
    else:
        mgmt = [u for u in await notif_svc.management_user_ids(conn, org_id) if str(u) != str(user["id"])]
        if mgmt:
            await notif_svc.notify(
                conn, org_id, "appeal.message", "appeal", appeal_id,
                {"author": user.get("full_name") or user.get("login"), "snippet": body[:140]}, mgmt)
    return {"id": str(row["id"]), "created_at": row["created_at"], "status": new_status}


async def close_appeal(conn, org_id, user: dict, appeal_id: str) -> dict:
    ap = await conn.fetchrow(
        "select id, status from appeals where id=$1::uuid and organization_id=$2", appeal_id, org_id)
    if ap is None:
        raise AppealsError("Обращение не найдено")
    await conn.execute("update appeals set status='closed', updated_at=now() where id=$1::uuid", appeal_id)
    await audit_svc.write_event(
        conn, org_id, user["id"], "update", "appeal", appeal_id,
        old_data={"status": ap["status"]}, new_data={"status": "closed"})
    return {"status": "closed"}
