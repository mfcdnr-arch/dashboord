"""Комментарии / обсуждение: и ко всему отчёту, и к КОНКРЕТНОЙ ЦИФРЕ (п. 8).

Доступ наследует видимость дашборда (RLS _can_view): кто видит дашборд — тот
читает обсуждение и может писать. Удаление — автор комментария либо
привилегированная роль. На новый комментарий уведомляется автор дашборда.
Лист-модуль (работает через conn), без своего HTTP.

**Комментарий к цифре помнит, О КАКОЙ цифре он был.** Виджет показывает
последний выпуск, поэтому замечание «здесь занижено, отделение переезжало»,
написанное в августе, через неделю висело бы рядом с сентябрьским числом и
вводило бы в заблуждение молча. Поэтому вместе с текстом сохраняются отчётная
дата (`period`) и строка (`row_label`), если человек провалился в район, а
лента показывает, относится ли замечание к тому числу, которое на экране
сейчас.

Второй ленты НЕ заводим: комментарии к цифрам живут в той же таблице и в том
же обсуждении дашборда — иначе часть разговора оказалась бы видна только
тому, кто догадался открыть нужный виджет.
"""
from __future__ import annotations

from ..audit import service as audit_svc
from ..notifications import service as notif_svc
from ._base import DashboardError
from ._rls import _can_view, _user_ctx

MAX_BODY = 4000


async def list_comments(conn, org_id, user: dict, dashboard_id: str,
                        limit: int = 50, offset: int = 0,
                        widget_id: str | None = None) -> dict:
    """Постранично: {total, limit, offset, items}. Новые сверху. can_delete —
    может ли текущий пользователь удалить конкретный комментарий.

    `widget_id` — лента ОДНОЙ цифры. Без него отдаётся всё обсуждение отчёта,
    включая замечания к цифрам: иначе часть разговора была бы видна только
    тому, кто догадался открыть нужный виджет.
    """
    if not await _can_view(conn, org_id, user, dashboard_id):
        raise DashboardError("Дашборд не найден")
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    ctx = await _user_ctx(conn, user)
    if widget_id:
        where = "c.dashboard_id=$1::uuid and c.widget_id=$4::uuid"
        total = await conn.fetchval(
            "select count(*) from dashboard_comments "
            "where dashboard_id=$1::uuid and widget_id=$2::uuid", dashboard_id, widget_id)
        args = [dashboard_id, limit, offset, widget_id]
    else:
        where = "c.dashboard_id=$1::uuid"
        total = await conn.fetchval(
            "select count(*) from dashboard_comments where dashboard_id=$1::uuid", dashboard_id)
        args = [dashboard_id, limit, offset]
    rows = await conn.fetch(
        "select c.id, c.body, c.created_at, c.user_id, c.widget_id, c.period, c.row_label, "
        "  u.login, u.full_name, w.name as widget_name "
        "from dashboard_comments c left join users u on u.id=c.user_id "
        "left join widgets w on w.id=c.widget_id "
        f"where {where} order by c.created_at desc limit $2 offset $3", *args)
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
            # Привязка к цифре: о каком виджете, за какую отчётную дату и по
            # какой строке шла речь. Пусто — замечание ко всему отчёту.
            "widget_id": str(c["widget_id"]) if c["widget_id"] else None,
            "widget_name": c["widget_name"],
            "period": c["period"].isoformat() if c["period"] else None,
            "row_label": c["row_label"],
        })
    return {"total": total, "limit": limit, "offset": offset, "items": items}


async def widget_comment_counts(conn, org_id, page_id: str) -> dict:
    """Сколько замечаний у каждого виджета страницы — пачкой на всю страницу.

    Значок 💬 в подвале виджета должен быть виден сразу: запрос на каждый
    виджет показал бы пустоту ровно тогда, когда на неё смотрят (тот же довод,
    что у подсказки ⓘ).
    """
    rows = await conn.fetch(
        "select c.widget_id, count(*) as n from dashboard_comments c "
        "join widgets w on w.id=c.widget_id "
        "where w.page_id=$1::uuid and w.organization_id=$2 group by c.widget_id", page_id, org_id)
    return {str(r["widget_id"]): r["n"] for r in rows}


async def add_comment(conn, org_id, user: dict, dashboard_id: str, body: str,
                      widget_id: str | None = None, period: str | None = None,
                      row_label: str | None = None) -> dict:
    """Замечание к отчёту или к конкретной цифре.

    `period` — отчётная дата, которую человек ВИДЕЛ на экране в момент
    написания. Её передаёт клиент вместе с текстом: сервер не может её
    восстановить постфактум (виджет мог быть отфильтрован периодом страницы
    или закреплён за срезом), а без неё замечание через неделю относилось бы
    к другому числу.
    """
    if not await _can_view(conn, org_id, user, dashboard_id):
        raise DashboardError("Дашборд не найден")
    body = (body or "").strip()
    if not body:
        raise DashboardError("Пустой комментарий")
    if len(body) > MAX_BODY:
        raise DashboardError(f"Слишком длинный комментарий (максимум {MAX_BODY} символов)")
    if widget_id is not None:
        # Виджет должен принадлежать ЭТОМУ дашборду: иначе замечание к чужой
        # цифре попало бы в чужое обсуждение, а видимость проверена по этому.
        ok = await conn.fetchval(
            "select 1 from widgets where id=$1::uuid and dashboard_id=$2::uuid and organization_id=$3",
            widget_id, dashboard_id, org_id)
        if not ok:
            raise DashboardError("Виджет не найден на этом дашборде")
    row = await conn.fetchrow(
        "insert into dashboard_comments(dashboard_id, user_id, body, widget_id, period, row_label) "
        "values($1::uuid, $2, $3, $4::uuid, $5::text::date, $6) returning id, created_at",
        dashboard_id, user["id"], body, widget_id, period, (row_label or None))
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
