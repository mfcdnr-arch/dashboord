"""Витрины (волна E): именованная подборка из N ЦЕЛЫХ дашбордов на одном
экране. НЕ путать с KioskView («📺 Витрина» внутри дашборда) — тот слайд-шоу
СТРАНИЦ ОДНОГО дашборда; здесь наоборот — несколько РАЗНЫХ дашбордов
показаны одновременно.

Видимость элементов наследует RLS дашбордов (visible_dashboard_ids/_can_view
из dashboards._rls): сама витрина как список видна всем, но чужие/
неопубликованные дашборды внутри неё для обычного пользователя просто не
показываются — как и остальная RLS в проекте, не палим их существование."""
from __future__ import annotations

from ..dashboards import service as dashboards_service
from ..dashboards._rls import _can_view, visible_dashboard_ids

MAX_NAME = 200


class ShowcasesError(Exception):
    """Доменная ошибка модуля витрин."""


async def create_showcase(conn, org_id, user_id, name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ShowcasesError("Пустое название")
    row = await conn.fetchrow(
        "insert into showcases(organization_id, name, created_by) values($1,$2,$3) "
        "returning id, name, created_at",
        org_id, name[:MAX_NAME], user_id)
    return {"id": str(row["id"]), "name": row["name"], "created_at": row["created_at"]}


async def list_showcases(conn, org_id) -> list:
    rows = await conn.fetch(
        "select s.id, s.name, s.created_at, s.updated_at, "
        "(select count(*) from showcase_items i where i.showcase_id=s.id) as items_count "
        "from showcases s where s.organization_id=$1 order by s.name", org_id)
    return [{"id": str(r["id"]), "name": r["name"], "created_at": r["created_at"],
            "updated_at": r["updated_at"], "items_count": r["items_count"]} for r in rows]


async def _get_or_404(conn, org_id, showcase_id: str):
    row = await conn.fetchrow(
        "select id, name, created_at, updated_at from showcases where id=$1::uuid and organization_id=$2",
        showcase_id, org_id)
    if row is None:
        raise ShowcasesError("Витрина не найдена")
    return row


async def _visible_items(conn, org_id, user: dict, showcase_id: str) -> list:
    """Элементы витрины, отфильтрованные RLS дашбордов; с папкой/объектом
    (та же связь folders->objects, что и в dashboards.list_dashboards —
    без неё «Состав» асимметричен списку дашбордов волны D)."""
    visible = await visible_dashboard_ids(conn, org_id, user)
    rows = await conn.fetch(
        "select i.id, i.dashboard_id, i.position, d.name as dashboard_name, "
        "fo.name as folder_name, ob.name as object_name, "
        "(select p.id from dashboard_pages p where p.dashboard_id=d.id "
        " order by p.position, p.created_at limit 1) as page_id, "
        "(select p.name from dashboard_pages p where p.dashboard_id=d.id "
        " order by p.position, p.created_at limit 1) as page_name "
        "from showcase_items i join dashboards d on d.id=i.dashboard_id "
        "left join folders fo on fo.id=d.folder_id left join objects ob on ob.id=fo.object_id "
        "where i.showcase_id=$1::uuid order by i.position, i.created_at", showcase_id)
    items = []
    for r in rows:
        if str(r["dashboard_id"]) not in visible:
            continue  # чужой/неопубликованный дашборд — молча пропускаем, не палим
        items.append({
            "id": str(r["id"]), "dashboard_id": str(r["dashboard_id"]), "position": r["position"],
            "dashboard_name": r["dashboard_name"],
            "folder_name": r["folder_name"], "object_name": r["object_name"],
            "page_id": str(r["page_id"]) if r["page_id"] else None,
            "page_name": r["page_name"],
        })
    return items


async def get_showcase(conn, org_id, user: dict, showcase_id: str) -> dict:
    s = await _get_or_404(conn, org_id, showcase_id)
    items = await _visible_items(conn, org_id, user, showcase_id)
    return {"id": str(s["id"]), "name": s["name"], "created_at": s["created_at"],
            "updated_at": s["updated_at"], "items": items}


async def get_showcase_data(conn, org_id, user: dict, showcase_id: str) -> dict:
    """Данные ВСЕХ панелей витрины ОДНИМ вызовом (перф: было N параллельных
    getPageData с фронта — теперь один батч, переиспользующий тот же
    compute_page_data, что и обычная страница дашборда)."""
    s = await _get_or_404(conn, org_id, showcase_id)
    items = await _visible_items(conn, org_id, user, showcase_id)
    out = []
    for it in items:
        entry = {"id": it["id"], "dashboard_id": it["dashboard_id"], "page_id": it["page_id"]}
        if it["page_id"] is None:
            entry["widgets"] = []
            entry["data"] = {}
        else:
            try:
                wlist = await dashboards_service.list_page_widgets(conn, org_id, it["page_id"], user)
                pdata = await dashboards_service.compute_page_data(conn, org_id, it["page_id"], user)
                entry["widgets"] = wlist["widgets"]
                entry["data"] = {w["id"]: w for w in pdata["widgets"]}
            except dashboards_service.DashboardError as e:
                entry["widgets"] = []
                entry["data"] = {}
                entry["error"] = str(e)
        out.append(entry)
    return {"id": str(s["id"]), "name": s["name"], "items": out}


async def delete_showcase(conn, org_id, showcase_id: str) -> None:
    await _get_or_404(conn, org_id, showcase_id)
    await conn.execute("delete from showcases where id=$1::uuid", showcase_id)


async def add_item(conn, org_id, user: dict, showcase_id: str, dashboard_id: str) -> dict:
    await _get_or_404(conn, org_id, showcase_id)
    if not await _can_view(conn, org_id, user, dashboard_id):
        raise ShowcasesError("Дашборд не найден")
    exists = await conn.fetchval(
        "select 1 from showcase_items where showcase_id=$1::uuid and dashboard_id=$2::uuid",
        showcase_id, dashboard_id)
    if exists:
        raise ShowcasesError("Этот дашборд уже в витрине")
    pos = await conn.fetchval(
        "select coalesce(max(position), -1) + 1 from showcase_items where showcase_id=$1::uuid", showcase_id)
    row = await conn.fetchrow(
        "insert into showcase_items(showcase_id, dashboard_id, position) values($1::uuid,$2::uuid,$3) "
        "returning id, position", showcase_id, dashboard_id, pos)
    await conn.execute("update showcases set updated_at=now() where id=$1::uuid", showcase_id)
    return {"id": str(row["id"]), "position": row["position"]}


async def remove_item(conn, org_id, showcase_id: str, item_id: str) -> None:
    await _get_or_404(conn, org_id, showcase_id)
    exists = await conn.fetchval(
        "select 1 from showcase_items where id=$1::uuid and showcase_id=$2::uuid", item_id, showcase_id)
    if not exists:
        raise ShowcasesError("Элемент витрины не найден")
    await conn.execute("delete from showcase_items where id=$1::uuid", item_id)
    await conn.execute("update showcases set updated_at=now() where id=$1::uuid", showcase_id)


async def reorder_items(conn, org_id, showcase_id: str, item_ids: list) -> None:
    """Задать ПОЛНЫЙ порядок элементов витрины одним вызовом (замена
    покомпонентного swap up/down — тот же эндпоинт обслуживает и кнопки
    ▲/▼ на фронте [пересчитавшие массив целиком], и drag-and-drop)."""
    await _get_or_404(conn, org_id, showcase_id)
    existing = await conn.fetch(
        "select id from showcase_items where showcase_id=$1::uuid", showcase_id)
    existing_ids = {str(r["id"]) for r in existing}
    if set(item_ids) != existing_ids or len(item_ids) != len(existing_ids):
        raise ShowcasesError("Список элементов не совпадает с составом витрины")
    async with conn.transaction():
        for pos, item_id in enumerate(item_ids):
            await conn.execute(
                "update showcase_items set position=$2 where id=$1::uuid and showcase_id=$3::uuid",
                item_id, pos, showcase_id)
    await conn.execute("update showcases set updated_at=now() where id=$1::uuid", showcase_id)
