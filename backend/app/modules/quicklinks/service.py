"""Быстрый доступ: куратор-меню коротких названий отчётов («MAX», «КЭП»,
«Статистика отделов»…), собираемое администратором из уже распознанных форм и
дашбордов — заказчик прямо сформулировал: «меню с названиями дашбордов,
которое можно составлять из названий файлов».

Пункт указывает либо на дашборд (`kind='dashboard'`), либо на bespoke-раздел
(`kind='section'`) — для того же «Статистика услуг ДНР», которому в таблице
`dashboards` соответствовать нечему. Список отдаётся ВСЕМ ролям, но КАЖДЫЙ
пункт фильтруется по видимости для смотрящего — читателя не должно смущать
меню с половиной неработающих ссылок, и по названию нельзя узнать о разделе,
куда доступа нет (тот же принцип, что у RLS дашбордов).
"""
from __future__ import annotations

from typing import List, Optional

from ..dashboards._rls import visible_dashboard_ids

# Разделы, на которые разрешено ссылаться: только отчётные/просмотровые, не
# административная кухня (пользователи/настройки/аудит и т.п.) — туда меню
# быстрого доступа вести не должно ни при каких правах.
ALLOWED_SECTIONS = {"dashboards", "instructions", "leadership", "showcases", "dnrstats", "archive"}
# Разделы без собственного гейта — видны всем сразу, как в боковом меню.
OPEN_SECTIONS = {"dashboards", "instructions"}


class QuickLinkError(Exception):
    pass


def _is_staff(user: dict) -> bool:
    return any(r in ("admin", "moderator", "superadmin") for r in user.get("roles", []))


async def list_links(conn, org_id, user: dict) -> List[dict]:
    rows = await conn.fetch(
        "select ql.id, ql.label, ql.kind, ql.dashboard_id, ql.section, d.name as dashboard_name "
        "from quick_links ql left join dashboards d on d.id = ql.dashboard_id "
        "where ql.organization_id=$1 order by ql.position, ql.created_at", org_id)
    if not rows:
        return []

    visible_dash = None
    if any(r["kind"] == "dashboard" for r in rows):
        visible_dash = await visible_dashboard_ids(conn, org_id, user)
    # Гейт разделов без собственного гейта в NAV — тот же критерий, что уже
    # решает видимость «Руководителю»/«Статистика услуг»/«Архива»/«Витрин» в
    # боковом меню (coarse-версия: staff всегда, иначе по галочке
    # `show_featured`). Точный разбор «есть ли хоть одна доступная витрина»
    # живёт во фронте у самого раздела — здесь достаточно не предлагать
    # пункт меню тому, кому раздел не откроется вовсе.
    section_ok = _is_staff(user) or bool(user.get("show_featured"))

    out = []
    for r in rows:
        if r["kind"] == "dashboard":
            if str(r["dashboard_id"]) not in visible_dash:
                continue
            out.append({"id": str(r["id"]), "label": r["label"], "kind": "dashboard",
                       "dashboard_id": str(r["dashboard_id"]), "dashboard_name": r["dashboard_name"]})
        else:
            if r["section"] not in OPEN_SECTIONS and not section_ok:
                continue
            out.append({"id": str(r["id"]), "label": r["label"], "kind": "section", "section": r["section"]})
    return out


async def create_link(conn, org_id, user_id, label: str, kind: str,
                      dashboard_id: Optional[str], section: Optional[str]) -> dict:
    label = (label or "").strip()
    if not label:
        raise QuickLinkError("Название пункта меню не может быть пустым")
    if kind == "dashboard":
        if not dashboard_id:
            raise QuickLinkError("Выберите дашборд")
        ok = await conn.fetchval(
            "select 1 from dashboards where id=$1::uuid and organization_id=$2", dashboard_id, org_id)
        if not ok:
            raise QuickLinkError("Дашборд не найден")
        section = None
    elif kind == "section":
        if section not in ALLOWED_SECTIONS:
            raise QuickLinkError(f"На раздел «{section}» ссылаться нельзя")
        dashboard_id = None
    else:
        raise QuickLinkError("Неизвестный тип пункта меню")

    pos = await conn.fetchval(
        "select coalesce(max(position),-1)+1 from quick_links where organization_id=$1", org_id)
    row = await conn.fetchrow(
        "insert into quick_links(organization_id, label, kind, dashboard_id, section, position, created_by) "
        "values($1,$2,$3,$4,$5,$6,$7) returning id",
        org_id, label, kind, dashboard_id, section, pos, user_id)
    return {"id": str(row["id"])}


async def delete_link(conn, org_id, link_id: str) -> None:
    await conn.execute(
        "delete from quick_links where id=$1::uuid and organization_id=$2", link_id, org_id)


async def reorder_links(conn, org_id, link_ids: List[str]) -> None:
    """Полный новый порядок (не swap) — тот же приём, что у витрин (2026-08-03):
    несовпадающий с реальным составом набор отклоняется, а не отражается частично."""
    existing = {str(r["id"]) for r in await conn.fetch(
        "select id from quick_links where organization_id=$1", org_id)}
    if set(link_ids) != existing:
        raise QuickLinkError("Список пунктов не совпадает с текущим составом меню")
    for i, lid in enumerate(link_ids):
        await conn.execute(
            "update quick_links set position=$1 where id=$2::uuid and organization_id=$3", i, lid, org_id)
