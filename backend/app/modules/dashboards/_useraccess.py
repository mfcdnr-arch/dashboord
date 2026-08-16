"""Доступ к дашбордам глазами ПОЛЬЗОВАТЕЛЯ (пп. 10–11 списка заказчика).

До сих пор доступ выдавался только «от дашборда»: открыть дашборд → «🔒 Доступ»
→ добавить человека. Чтобы понять, что видит один сотрудник, приходилось обойти
все дашборды по очереди — а выдать ему пять отчётов значило пять раз повторить
эту прогулку. Здесь тот же самый механизм грантов показан с другой стороны:
список всех дашбордов организации с отметкой, что этому человеку доступно.

Три решения, важные для правильности:

1. **Второй системы прав не заводим.** Читаем и пишем те же `access_grants`,
   а итоговую видимость считает `_rls.visible_dashboard_ids` — та же функция,
   которой пользуется список дашбордов. Иначе экран однажды показал бы
   «доступ есть», а человек увидел бы пустой список (или наоборот).

2. **Гранты на РОЛЬ отсюда не снимаются.** Они выданы не этому человеку, а
   всем носителям роли; снятие «чтобы убрать у Иванова» тихо отобрало бы
   доступ у всего отдела. Такие строки помечаются и не редактируются —
   роль правится в разделе «Пользователи», а грант на роль — на самом дашборде.

3. **Показываем не только галочку, но и последствие.** Привилегированная роль
   (admin/moderator/…) видит все дашборды независимо от грантов; неопубликованный
   дашборд зритель не увидит, даже когда грант выдан. Галочка, которая ничего не
   меняет, хуже её отсутствия, поэтому оба случая подписаны текстом.
"""
from __future__ import annotations

from typing import List, Optional

from ._base import DashboardError
from ._rls import PRIVILEGED_ROLES, visible_dashboard_ids


async def _target_user(conn, org_id, user_id: str) -> dict:
    row = await conn.fetchrow(
        "select id, login, full_name, is_active from users where id=$1::uuid and organization_id=$2",
        user_id, org_id)
    if row is None:
        raise DashboardError("Пользователь не найден")
    roles = await conn.fetch(
        "select r.id, r.code, r.name from user_roles ur join roles r on r.id=ur.role_id "
        "where ur.user_id=$1::uuid order by r.name", user_id)
    codes = {r["code"] for r in roles}
    return {
        "id": str(row["id"]), "login": row["login"], "full_name": row["full_name"],
        "is_active": row["is_active"],
        "roles": [(r["name"] or r["code"]) for r in roles],
        "role_ids": [r["id"] for r in roles],
        "privileged": bool(codes & PRIVILEGED_ROLES),
    }


async def user_dashboard_access(conn, org_id, user_id: str) -> dict:
    """Все дашборды организации с признаком доступа для указанного сотрудника."""
    target = await _target_user(conn, org_id, user_id)
    # Итоговая видимость — тем же кодом, что и список дашбордов у самого зрителя.
    visible = await visible_dashboard_ids(conn, org_id, {"id": user_id})
    rows = await conn.fetch(
        "select d.id, d.name, d.publication_status, d.featured, d.created_by, d.updated_at, "
        "fo.name as folder_name, ob.name as object_name, "
        "(select g.id from access_grants g where g.dashboard_id=d.id and g.scope='dashboard' "
        " and g.grantee_type='user' and g.user_id=$2::uuid limit 1) as user_grant_id, "
        "(select coalesce(array_agg(distinct coalesce(r.name, r.code)), '{}') "
        " from access_grants g join roles r on r.id=g.role_id "
        " where g.dashboard_id=d.id and g.scope='dashboard' and g.grantee_type='role' "
        "   and g.role_id = any($3::uuid[])) as via_roles, "
        "exists(select 1 from access_grants g where g.dashboard_id=d.id and g.scope='widget') as widget_limited "
        "from dashboards d "
        "left join folders fo on fo.id=d.folder_id "
        "left join objects ob on ob.id=fo.object_id "
        "where d.organization_id=$1 and d.publication_status <> 'archived' "
        "order by d.name",
        org_id, user_id, target["role_ids"])
    items = []
    for d in rows:
        did = str(d["id"])
        items.append({
            "dashboard_id": did,
            "name": d["name"],
            "publication_status": d["publication_status"],
            "featured": d["featured"],
            "folder_name": d["folder_name"],
            "object_name": d["object_name"],
            "granted": d["user_grant_id"] is not None,
            "grant_id": str(d["user_grant_id"]) if d["user_grant_id"] else None,
            "via_roles": list(d["via_roles"] or []),
            "is_author": str(d["created_by"]) == user_id if d["created_by"] else False,
            "widget_limited": d["widget_limited"],
            "visible": did in visible,
        })
    return {"user": {k: v for k, v in target.items() if k != "role_ids"}, "items": items}


async def set_user_dashboard_access(conn, org_id, actor_id, user_id: str,
                                    grant: Optional[List[str]] = None,
                                    revoke: Optional[List[str]] = None) -> dict:
    """Пакетная выдача/снятие ЛИЧНЫХ грантов сотруднику.

    Идемпотентно: повторная выдача уже выданного и снятие несуществующего —
    не ошибка, а «нечего делать» (панель отправляет разницу целиком, и падать
    на одной строке из десяти было бы хуже, чем пропустить её).

    Аудит и проверки пишет тот же `add_grant`/`remove_grant`, что и окно
    «🔒 Доступ» на дашборде — журнал не должен зависеть от того, каким экраном
    воспользовались.
    """
    from . import service  # ленивый импорт: service реэкспортирует этот модуль

    target = await _target_user(conn, org_id, user_id)
    granted, revoked = [], []
    for did in (grant or []):
        row = await conn.fetchrow(
            "select id from access_grants where dashboard_id=$1::uuid and scope='dashboard' "
            "and grantee_type='user' and user_id=$2::uuid", did, user_id)
        if row is not None:
            continue
        await service.add_grant(conn, org_id, actor_id, did, "user", None, user_id)
        granted.append(did)
    for did in (revoke or []):
        row = await conn.fetchrow(
            "select id from access_grants where dashboard_id=$1::uuid and scope='dashboard' "
            "and grantee_type='user' and user_id=$2::uuid", did, user_id)
        if row is None:
            continue  # личного гранта нет: либо уже снят, либо доступ идёт от роли
        await service.remove_grant(conn, org_id, did, str(row["id"]), actor_id)
        revoked.append(did)
    return {"granted": len(granted), "revoked": len(revoked),
            "user": {"id": target["id"], "login": target["login"]}}
