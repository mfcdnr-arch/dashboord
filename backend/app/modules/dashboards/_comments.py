"""Комментарии / обсуждение к дашбордам (лента).

Доступ наследует видимость дашборда (RLS _can_view): кто видит дашборд — тот
читает обсуждение и может писать. Удаление — автор комментария либо
привилегированная роль. На новый комментарий уведомляется автор дашборда.
Лист-модуль (работает через conn), без своего HTTP.
"""
from __future__ import annotations

from ..audit import service as audit_svc
from ..notifications import service as notif_svc
from ._base import DashboardError
from ._rls import _can_view, _user_ctx

MAX_BODY = 4000


async def list_comments(conn, org_id, user: dict, dashboard_id: str,
                        limit: int = 50, offset: int = 0) -> dict:
    """Постранично: {total, limit, offset, items}. Новые сверху. can_delete —
    может ли текущий пользователь удалить конкретный комментарий."""
    if not await _can_view(conn, org_id, user, dashboard_id):
        raise DashboardError("Дашборд не найден")
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    ctx = await _user_ctx(conn, user)
    total = await conn.fetchval(
        "select count(*) from dashboard_comments where dashboard_id=$1::uuid", dashboard_id)
    rows = await conn.fetch(
        "select c.id, c.body, c.created_at, c.user_id, u.login, u.full_name "
        "from dashboard_comments c left join users u on u.id=c.user_id "
        "where c.dashboard_id=$1::uuid order by c.created_at desc limit $2 offset $3",
        dashboard_id, limit, offset)
    items = []
    for c in rows:
        author_id = str(c["user_id"]) if c["user_id"] else None
        items.append({
            "id": str(c["id"]),
            "body": c["body"],
            "created_at": c["created_at"],
            "author_id": author_id,
            "author": (c["full_name"] or c["login"]) if c["user_id"] else "— (удалён)",
            "can_delete": ctx["privileged"] or (author_id is not None and author_id == str(user["id"])),
        })
    return {"total": total, "limit": limit, "offset": offset, "items": items}


async def add_comment(conn, org_id, user: dict, dashboard_id: str, body: str) -> dict:
    if not await _can_view(conn, org_id, user, dashboard_id):
        raise DashboardError("Дашборд не найден")
    body = (body or "").strip()
    if not body:
        raise DashboardError("Пустой комментарий")
    if len(body) > MAX_BODY:
        raise DashboardError(f"Слишком длинный комментарий (максимум {MAX_BODY} символов)")
    row = await conn.fetchrow(
        "insert into dashboard_comments(dashboard_id, user_id, body) "
        "values($1::uuid, $2, $3) returning id, created_at", dashboard_id, user["id"], body)
    # Уведомить автора дашборда (если это не он сам и он активен).
    owner = await conn.fetchrow(
        "select d.created_by, d.name from dashboards d where d.id=$1::uuid", dashboard_id)
    if owner and owner["created_by"] and str(owner["created_by"]) != str(user["id"]):
        active = await conn.fetchval(
            "select 1 from users where id=$1 and is_active", owner["created_by"])
        if active:
            await notif_svc.notify(
                conn, org_id, "dashboard.comment", "dashboard", dashboard_id,
                {"dashboard_name": owner["name"], "author": user.get("full_name") or user.get("login"),
                 "snippet": body[:140]},
                [owner["created_by"]])
    return {"id": str(row["id"]), "created_at": row["created_at"]}


async def delete_comment(conn, org_id, user: dict, dashboard_id: str, comment_id: str) -> None:
    c = await conn.fetchrow(
        "select c.user_id from dashboard_comments c join dashboards d on d.id=c.dashboard_id "
        "where c.id=$1::uuid and c.dashboard_id=$2::uuid and d.organization_id=$3",
        comment_id, dashboard_id, org_id)
    if c is None:
        raise DashboardError("Комментарий не найден")
    ctx = await _user_ctx(conn, user)
    is_author = c["user_id"] is not None and str(c["user_id"]) == str(user["id"])
    if not (ctx["privileged"] or is_author):
        raise DashboardError("Удалять можно только свой комментарий")
    await conn.execute("delete from dashboard_comments where id=$1::uuid", comment_id)
    await audit_svc.write_event(
        conn, org_id, user["id"], "delete", "dashboard_comment", comment_id,
        old_data={"dashboard_id": dashboard_id})
