"""RLS: разграничение доступа к дашбордам (вынесено из service.py).

Привилегированные роли видят все дашборды организации; остальные — только
созданные ими самими или те, на которые есть грант scope='dashboard' (напрямую
на пользователя или на одну из его ролей) И которые опубликованы. Виджеты/данные/
алерты наследуют видимость дашборда. Лист-модуль (работает только через conn)."""
from __future__ import annotations

PRIVILEGED_ROLES = {"admin", "moderator", "senior_moderator"}


async def _user_ctx(conn, user: dict) -> dict:
    rows = await conn.fetch(
        "select r.id, r.code from user_roles ur join roles r on r.id=ur.role_id where ur.user_id=$1",
        user["id"])
    codes = {r["code"] for r in rows}
    return {"codes": codes, "role_ids": [r["id"] for r in rows],
            "privileged": bool(codes & PRIVILEGED_ROLES)}


async def visible_dashboard_ids(conn, org_id, user: dict) -> set:
    """Множество id дашбордов, доступных пользователю на просмотр."""
    ctx = await _user_ctx(conn, user)
    if ctx["privileged"]:
        rows = await conn.fetch("select id from dashboards where organization_id=$1", org_id)
    else:
        # Непривилегированный видит: свой дашборд (в любом статусе — как автор)
        # ИЛИ выданный по гранту, но ТОЛЬКО опубликованный (модерационный гейт).
        rows = await conn.fetch(
            "select distinct d.id from dashboards d "
            "left join access_grants g on g.dashboard_id=d.id and g.scope='dashboard' "
            "  and ((g.grantee_type='user' and g.user_id=$2) "
            "       or (g.grantee_type='role' and g.role_id = any($3::uuid[]))) "
            "where d.organization_id=$1 and (d.created_by=$2 "
            "  or (g.id is not null and d.publication_status='published'))",
            org_id, user["id"], ctx["role_ids"])
    return {str(r["id"]) for r in rows}


async def _can_view(conn, org_id, user: dict, dashboard_id: str) -> bool:
    ctx = await _user_ctx(conn, user)
    if ctx["privileged"]:
        return bool(await conn.fetchval(
            "select 1 from dashboards where id=$1::uuid and organization_id=$2", dashboard_id, org_id))
    return bool(await conn.fetchval(
        "select 1 from dashboards d where d.id=$1::uuid and d.organization_id=$2 and ("
        "d.created_by=$3 or (d.publication_status='published' and "
        "exists(select 1 from access_grants g where g.dashboard_id=d.id "
        "and g.scope='dashboard' and ((g.grantee_type='user' and g.user_id=$3) "
        "or (g.grantee_type='role' and g.role_id = any($4::uuid[]))))))",
        dashboard_id, org_id, user["id"], ctx["role_ids"]))
