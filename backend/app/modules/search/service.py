"""Быстрый поиск по системе (п. 9, Ctrl+K).

До этого поиск существовал только ВНУТРИ разделов: список дашбордов искал
среди дашбордов, список показателей — среди показателей, и найти нужное можно
было, только сначала угадав, в каком разделе оно лежит. Здесь — один запрос
сразу по пяти сущностям.

**RLS соблюдён на границе, а не «на глаз».** Дашборды фильтруются той же
`visible_dashboard_ids`, что и список дашбордов; страницы и виджеты наследуют
видимость своего дашборда, а виджеты вдобавок — whitelist по гранту
(`visible_widget_ids`), иначе поиск стал бы обходным путём: узнать имя чужого
виджета, набрав в строке поиска первые буквы. Объекты и показатели читает
любой авторизованный — так же, как их читают собственные разделы списком.

**Каждая категория ограничена небольшим числом результатов.** Это подсказка
для быстрого перехода, а не полноценный поисковый индекс: длинный список
листать в выпадающем окне неудобно, а первых нескольких почти всегда
достаточно, чтобы узнать нужное.
"""
from __future__ import annotations

from typing import List

from ..dashboards._rls import visible_dashboard_ids, visible_widget_ids

MIN_QUERY = 2
LIMIT = 6


async def search(conn, org_id, user: dict, q: str) -> dict:
    q = (q or "").strip()
    if len(q) < MIN_QUERY:
        return {"dashboards": [], "pages": [], "widgets": [], "objects": [], "metrics": []}

    allowed = await visible_dashboard_ids(conn, org_id, user)
    if not allowed:
        dashboards: List[dict] = []
        pages: List[dict] = []
        widgets: List[dict] = []
    else:
        dashboards = await _dashboards(conn, org_id, q, allowed)
        pages = await _pages(conn, org_id, q, allowed)
        widgets = await _widgets(conn, org_id, user, q, allowed)

    return {
        "dashboards": dashboards,
        "pages": pages,
        "widgets": widgets,
        "objects": await _objects(conn, org_id, q),
        "metrics": await _metrics(conn, org_id, q),
    }


# Совпадение с НАЧАЛА названия — первым: кто ищет «Внедрение», обычно имеет в
# виду «Внедрение сервиса МАХ», а не «Отчёт о внедрении» где-то в середине.
# Алиас передаётся явно — колонка `name` неоднозначна при join, а имя таблицы
# в каждом запросе своё.
def _order(alias: str) -> str:
    return f"order by ({alias}.name ilike $3 || '%') desc, {alias}.name limit $4"


async def _dashboards(conn, org_id, q: str, allowed: set) -> List[dict]:
    rows = await conn.fetch(
        "select d.id, d.name, o.name as object_name, f.name as folder_name "
        "from dashboards d left join folders f on f.id=d.folder_id "
        "left join objects o on o.id=f.object_id "
        "where d.organization_id=$1 and d.id = any($2::uuid[]) and d.name ilike '%' || $3 || '%' "
        f"{_order('d')}",
        org_id, list(allowed), q, LIMIT)
    return [{"id": str(r["id"]), "name": r["name"],
             "object_name": r["object_name"], "folder_name": r["folder_name"]} for r in rows]


async def _pages(conn, org_id, q: str, allowed: set) -> List[dict]:
    rows = await conn.fetch(
        "select p.id, p.name, d.id as dashboard_id, d.name as dashboard_name "
        "from dashboard_pages p join dashboards d on d.id=p.dashboard_id "
        "where d.organization_id=$1 and d.id = any($2::uuid[]) and p.name ilike '%' || $3 || '%' "
        f"{_order('p')}",
        org_id, list(allowed), q, LIMIT)
    return [{"id": str(r["id"]), "name": r["name"],
             "dashboard_id": str(r["dashboard_id"]), "dashboard_name": r["dashboard_name"]} for r in rows]


async def _widgets(conn, org_id, user: dict, q: str, allowed: set) -> List[dict]:
    rows = await conn.fetch(
        "select w.id, w.name, w.widget_type, w.dashboard_id, d.name as dashboard_name, "
        "  w.page_id, p.name as page_name "
        "from widgets w join dashboards d on d.id=w.dashboard_id "
        "left join dashboard_pages p on p.id=w.page_id "
        "where w.organization_id=$1 and w.dashboard_id = any($2::uuid[]) "
        "  and w.name ilike '%' || $3 || '%' "
        f"{_order('w')}",
        # Берём с запасом: часть отсеется whitelist'ом по гранту ниже, а
        # результатов должно остаться LIMIT.
        org_id, list(allowed), q, LIMIT * 3)

    out: List[dict] = []
    whitelist_cache: dict = {}
    for r in rows:
        did = str(r["dashboard_id"])
        if did not in whitelist_cache:
            whitelist_cache[did] = await visible_widget_ids(conn, org_id, user, did)
        wl = whitelist_cache[did]
        if wl is not None and str(r["id"]) not in wl:
            continue
        out.append({
            "id": str(r["id"]), "name": r["name"], "widget_type": r["widget_type"],
            "dashboard_id": did, "dashboard_name": r["dashboard_name"],
            "page_id": str(r["page_id"]) if r["page_id"] else None, "page_name": r["page_name"],
        })
        if len(out) >= LIMIT:
            break
    return out


async def _objects(conn, org_id, q: str) -> List[dict]:
    rows = await conn.fetch(
        "select id, name from objects where organization_id=$1 and name ilike '%' || $2 || '%' "
        "order by (name ilike $2 || '%') desc, name limit $3",
        org_id, q, LIMIT)
    return [{"id": str(r["id"]), "name": r["name"]} for r in rows]


async def _metrics(conn, org_id, q: str) -> List[dict]:
    rows = await conn.fetch(
        "select id, code, name from metrics where organization_id=$1 "
        "  and (name ilike '%' || $2 || '%' or code ilike '%' || $2 || '%') "
        "order by (name ilike $2 || '%' or code ilike $2 || '%') desc, name limit $3",
        org_id, q, LIMIT)
    return [{"id": str(r["id"]), "code": r["code"], "name": r["name"]} for r in rows]
