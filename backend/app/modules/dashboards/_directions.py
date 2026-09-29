"""Направления дашбордов — группы внутри раздела «Дашборды» (этап 3, 29.09.2026).

Решения заказчика 23.09: направление — группа ВНУТРИ «Дашбордов» (меню не
растёт); у дашборда одно направление или никакого; доступ прежний —
направление только группирует, видимость решают гранты на дашборды; система
предлагает разложить существующие дашборды, администратор подтверждает.

🔴 Главное правило здесь — не проговориться. Название направления и число
«отчётов: N» не должны сообщать зрителю о дашбордах, которых ему не видно
(тот же класс, что закрытый 20.09 поиск по служебным сущностям): счёт идёт
ТОЛЬКО по видимым ему дашбордам, а пустое для него направление не
показывается вовсе. Управляющий видит все направления, включая пустые, —
иначе завести группу и наполнить её было бы нечем.

Архивные дашборды не считаются: основной список их не показывает, и число в
заголовке группы разошлось бы с тем, что под ним нарисовано.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from ._base import DashboardError
from ._rls import _user_ctx, visible_dashboard_ids

MAX_NAME = 120


def clean_name(name: Optional[str]) -> str:
    """Имя направления: внешние и повторные пробелы убираются, пустое — отказ."""
    text = re.sub(r"\s+", " ", (name or "")).strip()
    if not text:
        raise DashboardError("Укажите название направления")
    if len(text) > MAX_NAME:
        raise DashboardError(f"Название направления длиннее {MAX_NAME} знаков")
    return text


async def _by_name(conn, org_id, name: str) -> Optional[dict]:
    row = await conn.fetchrow(
        "select id, name from dashboard_directions "
        "where organization_id=$1 and lower(btrim(name)) = lower(btrim($2))", org_id, name)
    return dict(row) if row else None


async def _require(conn, org_id, direction_id: str) -> dict:
    row = await conn.fetchrow(
        "select id, name, description, position from dashboard_directions "
        "where id=$1::uuid and organization_id=$2", direction_id, org_id)
    if row is None:
        raise DashboardError("Направление не найдено")
    return dict(row)


async def list_directions(conn, org_id, user: dict) -> dict:
    """Направления с числом ВИДИМЫХ пользователю дашбордов.

    {items: [{id, name, description, position, dashboards}], without: N,
    manage: bool} — `without`: сколько видимых дашбордов без направления.
    """
    ctx = await _user_ctx(conn, user)
    visible = list(await visible_dashboard_ids(conn, org_id, user))
    rows = await conn.fetch(
        "select dd.id, dd.name, dd.description, dd.position, "
        "  count(d.id) filter (where d.id = any($2::uuid[]) and d.publication_status <> 'archived') "
        "    as dashboards "
        "from dashboard_directions dd left join dashboards d on d.direction_id = dd.id "
        "where dd.organization_id=$1 group by dd.id "
        "order by dd.position, lower(dd.name)", org_id, visible)
    items = [dict(r) for r in rows]
    if not ctx["privileged"]:
        items = [r for r in items if r["dashboards"] > 0]
    without = await conn.fetchval(
        "select count(*) from dashboards where organization_id=$1 and id = any($2::uuid[]) "
        "and publication_status <> 'archived' and direction_id is null", org_id, visible)
    return {"items": items, "without": int(without or 0), "manage": ctx["privileged"]}


async def create_direction(conn, org_id, user_id, name: str,
                           description: Optional[str] = None) -> dict:
    name = clean_name(name)
    if await _by_name(conn, org_id, name):
        raise DashboardError(f"Направление «{name}» уже есть")
    # Новое — в конец: порядок групп задал человек, и новая не должна
    # вставать перед главной.
    pos = await conn.fetchval(
        "select coalesce(max(position), -1) + 1 from dashboard_directions where organization_id=$1",
        org_id)
    row = await conn.fetchrow(
        "insert into dashboard_directions(organization_id, name, description, position, created_by) "
        "values($1,$2,$3,$4,$5) returning id, name, description, position",
        org_id, name, (description or "").strip() or None, pos, user_id)
    return {**dict(row), "dashboards": 0}


async def update_direction(conn, org_id, direction_id: str, patch: dict) -> dict:
    """Переименовать или описать. `patch` — только присланные поля."""
    await _require(conn, org_id, direction_id)
    sets, params = [], [direction_id, org_id]
    if "name" in patch:
        name = clean_name(patch["name"])
        other = await _by_name(conn, org_id, name)
        if other and str(other["id"]) != str(direction_id):
            raise DashboardError(f"Направление «{name}» уже есть")
        params.append(name); sets.append(f"name=${len(params)}")
    if "description" in patch:
        params.append((patch["description"] or "").strip() or None)
        sets.append(f"description=${len(params)}")
    if not sets:
        raise DashboardError("Нечего изменять")
    row = await conn.fetchrow(
        f"update dashboard_directions set {', '.join(sets)}, updated_at=now() "
        "where id=$1::uuid and organization_id=$2 returning id, name, description, position", *params)
    return dict(row)


async def delete_direction(conn, org_id, direction_id: str) -> dict:
    """Удалить направление. Дашборды остаются — без направления (FK on delete set null)."""
    await _require(conn, org_id, direction_id)
    freed = await conn.fetchval(
        "select count(*) from dashboards where direction_id=$1::uuid", direction_id)
    await conn.execute(
        "delete from dashboard_directions where id=$1::uuid and organization_id=$2",
        direction_id, org_id)
    return {"deleted": True, "dashboards_freed": int(freed or 0)}


async def reorder_directions(conn, org_id, ids: List[str]) -> dict:
    """Порядок групп — как в списке `ids`; не названные остаются после них."""
    known = {str(r["id"]) for r in await conn.fetch(
        "select id from dashboard_directions where organization_id=$1", org_id)}
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise DashboardError("Направление не найдено")
    for pos, did in enumerate(ids):
        await conn.execute(
            "update dashboard_directions set position=$2, updated_at=now() where id=$1::uuid",
            did, pos)
    rest = [i for i in known if i not in set(ids)]
    for extra, did in enumerate(sorted(rest)):
        await conn.execute(
            "update dashboard_directions set position=$2, updated_at=now() where id=$1::uuid",
            did, len(ids) + extra)
    return {"ordered": len(ids)}


async def resolve_direction(conn, org_id, user_id, direction_id: Optional[str],
                            new_name: Optional[str]) -> Optional[str]:
    """id направления для создания/назначения: существующее по id или по имени,
    новое по имени. Имя, совпавшее с существующим, НЕ плодит второе — берётся оно."""
    if new_name and new_name.strip():
        name = clean_name(new_name)
        found = await _by_name(conn, org_id, name)
        if found:
            return str(found["id"])
        made = await create_direction(conn, org_id, user_id, name)
        return str(made["id"])
    if direction_id:
        await _require(conn, org_id, direction_id)
        return str(direction_id)
    return None


async def assign(conn, org_id, user_id, dashboard_ids: List[str], direction_id: Optional[str],
                 new_name: Optional[str] = None) -> dict:
    """Назначить направление дашбордам (или снять: direction_id=None без имени).

    Одной операцией: вызывающий держит транзакцию. 🔴 Массовое перемещение в
    папку сделано циклом запросов с экрана — сбой на середине оставляет часть
    переложенной без сообщения, какую. Здесь либо все, либо ни одного: сперва
    проверяются ВСЕ дашборды, потом пишется.
    """
    ids = list(dict.fromkeys(str(i) for i in dashboard_ids if i))
    if not ids:
        raise DashboardError("Не выбрано ни одного дашборда")
    found = {str(r["id"]) for r in await conn.fetch(
        "select id from dashboards where organization_id=$1 and id = any($2::uuid[])", org_id, ids)}
    if len(found) != len(ids):
        raise DashboardError("Дашборд не найден")
    target = await resolve_direction(conn, org_id, user_id, direction_id, new_name)
    await conn.execute(
        "update dashboards set direction_id=$2::uuid, updated_at=now() "
        "where organization_id=$1 and id = any($3::uuid[]) and direction_id is distinct from $2::uuid",
        org_id, target, ids)
    name = await conn.fetchval(
        "select name from dashboard_directions where id=$1::uuid", target) if target else None
    return {"direction_id": target, "direction_name": name, "dashboards": len(ids)}


# ─────────────────────────────────────────────────────────────────────────────
# Предложение: система раскладывает, администратор подтверждает
# ─────────────────────────────────────────────────────────────────────────────

# Разделители в названиях объектов и дашбордов: «Статистика услуг — МВД»,
# «РЦО — окна и часы», «РЦО: ежедневный отчёт». Семейство — то, что до них.
_FAMILY_SPLIT = re.compile(r"\s+[—–-]\s+|:\s+")


def family_of(object_name: Optional[str], dashboard_name: str) -> str:
    """Семейство дашборда — кандидат в направление.

    По ИМЕНИ ОБЪЕКТА, а не дашборда: объекты в системе и называются
    «группа — уточнение» («Статистика услуг — МВД»), а у дашборда имя
    свободное. Нет объекта — по имени дашборда.
    """
    source = (object_name or "").strip() or (dashboard_name or "").strip()
    head = _FAMILY_SPLIT.split(source, maxsplit=1)[0].strip()
    return head or source


async def proposal(conn, org_id) -> dict:
    """Как разложить дашборды БЕЗ направления. Ничего не пишет.

    {groups: [{name, direction_id|None, why, dashboards: [{id, name, object_name}]}],
    unassigned: N}. Имя группы, совпавшее с существующим направлением, ведёт в
    него (`direction_id`), а не создаёт второе.
    """
    rows = await conn.fetch(
        "select d.id, d.name, ob.name as object_name from dashboards d "
        "left join folders fo on fo.id=d.folder_id left join objects ob on ob.id=fo.object_id "
        "where d.organization_id=$1 and d.direction_id is null "
        "and d.publication_status <> 'archived' order by lower(d.name)", org_id)
    existing = {r["name"].strip().lower(): r for r in await conn.fetch(
        "select id, name from dashboard_directions where organization_id=$1", org_id)}
    groups: Dict[str, dict] = {}
    for r in rows:
        fam = family_of(r["object_name"], r["name"])
        key = fam.lower()
        g = groups.setdefault(key, {"name": fam, "direction_id": None, "dashboards": [],
                                    "objects": set()})
        g["dashboards"].append({"id": str(r["id"]), "name": r["name"],
                                "object_name": r["object_name"]})
        if r["object_name"]:
            g["objects"].add(r["object_name"])
    out = []
    for key, g in groups.items():
        hit = existing.get(key)
        if hit:
            g["direction_id"], g["name"] = str(hit["id"]), hit["name"]
        objs = sorted(g.pop("objects"))
        if hit:
            why = f"Такое направление уже есть — «{hit['name']}»."
        elif objs:
            why = ("Общее начало имени объекта: " + ", ".join(f"«{o}»" for o in objs[:4])
                   + (f" и ещё {len(objs) - 4}" if len(objs) > 4 else "") + ".")
        else:
            why = "По началу названия дашборда — объекта у него нет."
        out.append({**g, "why": why})
    # Сначала группы, где дашбордов больше: они и есть «направления», одиночки —
    # скорее кандидаты, которые человек переименует или соберёт вместе.
    out.sort(key=lambda g: (-len(g["dashboards"]), g["name"].lower()))
    return {"groups": out, "unassigned": len(rows)}


async def apply_proposal(conn, org_id, user_id, groups: List[dict]) -> dict:
    """Применить подтверждённую раскладку: [{name, dashboard_ids}] одной операцией."""
    created, assigned = 0, 0
    for g in groups:
        ids = [i for i in (g.get("dashboard_ids") or []) if i]
        if not ids:
            continue
        name = clean_name(g.get("name"))
        before = await _by_name(conn, org_id, name)
        res = await assign(conn, org_id, user_id, ids, None, name)
        created += 0 if before else 1
        assigned += res["dashboards"]
    if not assigned:
        raise DashboardError("Не отмечено ни одного дашборда")
    return {"directions_created": created, "dashboards_assigned": assigned}


async def suggest_for_object(conn, org_id, object_id: Optional[str]) -> Optional[dict]:
    """Направление по умолчанию для нового дашборда объекта (мастер «✨ Собрать»).

    Если у других дашбордов этого объекта направление есть — то, что у
    большинства; иначе — существующее направление с именем семейства объекта.
    Ничего не создаёт: новое заводит человек.
    """
    if not object_id:
        return None
    # Дашборд объекта — по папке ИЛИ по данным его виджетов: папку мастер ставит
    # по документам объекта, и без них (данные перенесены строками) связь
    # через папку теряется.
    row = await conn.fetchrow(
        "select dd.id, dd.name, count(distinct d.id) as n from dashboards d "
        "join dashboard_directions dd on dd.id=d.direction_id "
        "where d.organization_id=$1 and d.publication_status <> 'archived' and ("
        "  d.folder_id in (select id from folders where object_id=$2::uuid) "
        "  or exists (select 1 from widgets w join dataset_releases r "
        "             on r.code = w.config->>'dataset_code' and r.organization_id = d.organization_id "
        "             where w.dashboard_id = d.id and r.object_id = $2::uuid)) "
        "group by dd.id, dd.name order by n desc, lower(dd.name) limit 1", org_id, object_id)
    if row:
        return {"id": str(row["id"]), "name": row["name"], "why": "так разложены другие дашборды объекта"}
    obj = await conn.fetchval(
        "select name from objects where id=$1::uuid and organization_id=$2", object_id, org_id)
    if not obj:
        return None
    fam = family_of(obj, obj)
    hit = await _by_name(conn, org_id, fam)
    if hit:
        return {"id": str(hit["id"]), "name": hit["name"], "why": "совпадает с началом имени объекта"}
    return {"id": None, "name": fam, "why": "новое — по началу имени объекта"}
