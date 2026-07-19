"""Сервис «Аудит действий»: чтение журнала audit_log.

Журнал наполняют триггеры БД (fn_audit_generic) при изменении аудируемых
сущностей (widgets, dashboards, object_acl). Автор берётся из GUC
app.current_user_id, которую проставляет db.acquire(user_id). Здесь — только
чтение: фильтруемый список с пагинацией, фасеты для фильтров и детальный
пофайловый diff одной записи.
"""
from __future__ import annotations

import json
from typing import Any, Optional

# Человекочитаемые типы сущностей (для фасета; на фронте дублируются подписи).
ENTITY_LABELS = {
    "dashboard": "Дашборд",
    "widget": "Виджет",
    "object_acl": "Права доступа",
}
# Все значения enum audit_action (порядок — для фасета фильтра).
ACTIONS = ["create", "update", "delete", "publish", "grant_access", "revoke_access", "view"]

# Технические поля, изменение которых не считаем содержательным при вычислении
# сводки изменённых полей (они меняются при любой правке).
NOISE_FIELDS = {"updated_at"}

MAX_LIMIT = 200


class AuditError(Exception):
    """Доменная ошибка модуля аудита."""


def _as_dict(v: Any) -> dict:
    """jsonb из asyncpg приходит строкой (кодек не зарегистрирован) — нормализуем."""
    if v is None:
        return {}
    if isinstance(v, dict):
        return v
    if isinstance(v, (str, bytes)):
        try:
            d = json.loads(v)
            return d if isinstance(d, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _entity_name(old: dict, new: dict) -> Optional[str]:
    """Имя сущности для читаемости строки журнала (если есть в снимке)."""
    return new.get("name") or old.get("name") or None


def _changed_fields(old: dict, new: dict, *, drop_noise: bool = True) -> list[str]:
    keys = set(old) | set(new)
    changed = [k for k in keys if old.get(k) != new.get(k)]
    if drop_noise:
        changed = [k for k in changed if k not in NOISE_FIELDS]
    return sorted(changed)


async def list_events(
    conn,
    org_id,
    *,
    actor: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    action: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Отфильтрованный, постранично выданный журнал + total и фасеты фильтров."""
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, offset)

    where = ["a.organization_id = $1"]
    params: list[Any] = [org_id]

    def add(cond_tmpl: str, value: Any) -> None:
        params.append(value)
        where.append(cond_tmpl.format(n=len(params)))

    if actor:
        add("a.actor_user_id = ${n}::uuid", actor)
    if entity_type:
        add("a.entity_type = ${n}", entity_type)
    if entity_id:
        add("a.entity_id = ${n}::uuid", entity_id)
    if action:
        if action not in ACTIONS:
            raise AuditError(f"Недопустимое действие: {action}")
        add("a.action = ${n}::audit_action", action)
    if date_from:
        add("a.created_at >= ${n}::timestamptz", date_from)
    if date_to:
        # включительно по дате: строгий верх — начало следующего дня передаёт клиент
        add("a.created_at < ${n}::timestamptz", date_to)

    where_sql = " and ".join(where)

    total = await conn.fetchval(f"select count(*) from audit_log a where {where_sql}", *params)

    rows = await conn.fetch(
        f"""
        select a.id, a.action, a.entity_type, a.entity_id, a.actor_user_id,
               u.login as actor_login, u.full_name as actor_name,
               a.ip_address, a.created_at, a.old_data, a.new_data
        from audit_log a
        left join users u on u.id = a.actor_user_id
        where {where_sql}
        order by a.created_at desc, a.id
        limit ${len(params) + 1} offset ${len(params) + 2}
        """,
        *params, limit, offset,
    )

    items = []
    for r in rows:
        old = _as_dict(r["old_data"])
        new = _as_dict(r["new_data"])
        items.append({
            "id": str(r["id"]),
            "action": r["action"],
            "entity_type": r["entity_type"],
            "entity_id": str(r["entity_id"]),
            "entity_name": _entity_name(old, new),
            "actor_user_id": str(r["actor_user_id"]) if r["actor_user_id"] else None,
            "actor_login": r["actor_login"],
            "actor_name": r["actor_name"],
            "ip_address": r["ip_address"],
            "created_at": r["created_at"],
            "changed_fields": _changed_fields(old, new) if r["action"] == "update" else [],
        })

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
        "facets": await _facets(conn, org_id),
    }


async def _facets(conn, org_id) -> dict:
    """Наборы для выпадающих фильтров: актёры и типы сущностей, встречающиеся
    в журнале организации, плюс полный список действий."""
    actors = await conn.fetch(
        "select distinct u.id, u.login, u.full_name "
        "from audit_log a join users u on u.id = a.actor_user_id "
        "where a.organization_id = $1 order by u.login",
        org_id,
    )
    ets = await conn.fetch(
        "select distinct entity_type from audit_log where organization_id = $1 order by 1",
        org_id,
    )
    return {
        "actors": [{"id": str(a["id"]), "login": a["login"], "full_name": a["full_name"]} for a in actors],
        "entity_types": [{"code": e["entity_type"], "label": ENTITY_LABELS.get(e["entity_type"], e["entity_type"])} for e in ets],
        "actions": ACTIONS,
    }


async def get_event(conn, org_id, event_id: str) -> dict:
    """Одна запись журнала с полным пофайловым diff (old → new)."""
    r = await conn.fetchrow(
        """
        select a.id, a.action, a.entity_type, a.entity_id, a.actor_user_id,
               u.login as actor_login, u.full_name as actor_name,
               a.ip_address, a.created_at, a.old_data, a.new_data
        from audit_log a
        left join users u on u.id = a.actor_user_id
        where a.id = $1::uuid and a.organization_id = $2
        """,
        event_id, org_id,
    )
    if r is None:
        raise AuditError("Запись аудита не найдена")

    old = _as_dict(r["old_data"])
    new = _as_dict(r["new_data"])
    changed = set(_changed_fields(old, new, drop_noise=False))
    fields = sorted(set(old) | set(new))
    diff = [{
        "field": f,
        "old": old.get(f),
        "new": new.get(f),
        "changed": f in changed,
    } for f in fields]

    return {
        "id": str(r["id"]),
        "action": r["action"],
        "entity_type": r["entity_type"],
        "entity_id": str(r["entity_id"]),
        "entity_name": _entity_name(old, new),
        "actor_user_id": str(r["actor_user_id"]) if r["actor_user_id"] else None,
        "actor_login": r["actor_login"],
        "actor_name": r["actor_name"],
        "ip_address": r["ip_address"],
        "created_at": r["created_at"],
        "diff": diff,
    }
