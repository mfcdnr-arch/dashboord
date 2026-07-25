"""Сервис уведомлений: лента получателя + создание событий (notify).

Хранилище: notification_events (событие) + notification_recipients (по кому,
прочитано/нет). notify() переиспользуют другие модули (напр. проверка свежести).
"""
from __future__ import annotations

import json
from typing import Any, Optional

# Человекочитаемые подписи типов событий (для UI).
EVENT_LABELS = {
    "data.stale": "Данные устарели",
    "data.missing": "Ожидаемые данные не поступили",
    "data.retention": "Очистка старых данных (ретенция)",
    "widget.created.no_explicit_access": "Новый виджет без прав доступа",
    "dashboard.comment": "Новый комментарий к дашборду",
}


async def notify(conn, org_id, event_type: str, entity_type: str, entity_id: str,
                 payload: dict, user_ids: list) -> Optional[str]:
    """Создать событие и раздать получателям. Возвращает id события (или None,
    если получателей нет)."""
    if not user_ids:
        return None
    ev = await conn.fetchval(
        "insert into notification_events(organization_id, event_type, entity_type, entity_id, payload) "
        "values($1,$2,$3,$4::uuid,$5::jsonb) returning id",
        org_id, event_type, entity_type, entity_id,
        json.dumps(payload, ensure_ascii=False, default=str))
    for uid in user_ids:
        await conn.execute(
            "insert into notification_recipients(notification_event_id, user_id) values($1,$2)", ev, uid)
    return str(ev)


async def recent_event_exists(conn, org_id, event_type: str, entity_id: str, days: int) -> bool:
    """Есть ли такое же событие по этой сущности за последние N дней (антидубль)."""
    return bool(await conn.fetchval(
        "select 1 from notification_events where organization_id=$1 and event_type=$2 "
        "and entity_id=$3::uuid and created_at > now() - make_interval(days => $4) limit 1",
        org_id, event_type, entity_id, days))


async def management_user_ids(conn, org_id) -> list:
    """Пользователи-получатели служебных уведомлений: admin/moderator/senior_moderator."""
    rows = await conn.fetch(
        "select distinct u.id from users u join user_roles ur on ur.user_id=u.id "
        "join roles r on r.id=ur.role_id "
        "where u.organization_id=$1 and u.is_active and r.code in ('admin','moderator','senior_moderator')",
        org_id)
    return [r["id"] for r in rows]


async def list_for_user(conn, user_id, limit: int = 50) -> dict:
    rows = await conn.fetch(
        "select r.id as recipient_id, e.event_type, e.entity_type, e.entity_id, "
        "e.payload, e.created_at, r.is_read "
        "from notification_recipients r join notification_events e on e.id=r.notification_event_id "
        "where r.user_id=$1 order by r.is_read, e.created_at desc limit $2",
        user_id, limit)
    unread = await conn.fetchval(
        "select count(*) from notification_recipients where user_id=$1 and not is_read", user_id)
    items = []
    for r in rows:
        pl = r["payload"]
        if isinstance(pl, str):
            try:
                pl = json.loads(pl)
            except ValueError:
                pl = {}
        items.append({
            "recipient_id": str(r["recipient_id"]),
            "event_type": r["event_type"],
            "label": EVENT_LABELS.get(r["event_type"], r["event_type"]),
            "entity_type": r["entity_type"],
            "entity_id": str(r["entity_id"]) if r["entity_id"] else None,
            "payload": pl,
            "created_at": r["created_at"],
            "is_read": r["is_read"],
        })
    return {"unread": unread, "items": items}


async def mark_read(conn, user_id, recipient_id: str) -> None:
    await conn.execute(
        "update notification_recipients set is_read=true, read_at=now() "
        "where id=$1::uuid and user_id=$2", recipient_id, user_id)


async def mark_all_read(conn, user_id) -> dict:
    res = await conn.execute(
        "update notification_recipients set is_read=true, read_at=now() "
        "where user_id=$1 and not is_read", user_id)
    return {"ok": True}
