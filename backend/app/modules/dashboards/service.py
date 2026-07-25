"""Сервис дашбордов: CRUD дашбордов/страниц/виджетов + вычисление данных виджета.

Данные виджета берутся из:
- метрики (по коду, одобренная версия) — для KPI и план-факта;
- датасета (активный выпуск) — для таблицы и графиков (категория = название строки,
  значение = выбранное числовое поле).
Типы виджетов (widget_type): kpi | table | bar | line | pie | plan_fact.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ... import cache
from ..audit import service as audit_svc
from ..metrics import resolver as mr
from ..metrics.parser import FormulaError, extract_dependencies, parse
# Кластеры, вынесенные из этого файла (рефактор). Реэкспортируем, чтобы внешние
# вызовы `service.<name>` и `from .service import <name>` продолжали работать.
from ._alerts import (  # noqa: F401
    _ALERT_OP_TXT, _ALERT_STYLES, _alert_match, _alert_measure, _cfg, evaluate_alert,
)
from ._base import ANNOTATION_TYPES, WIDGET_TYPES, DashboardError  # noqa: F401
from ._rls import PRIVILEGED_ROLES, _can_view, _user_ctx, visible_dashboard_ids  # noqa: F401
from ._widgetdata import (  # noqa: F401
    _best_metric_version, _compute_widget, _dataset_multi_series, _dataset_period_series,
    _dataset_series, _dataset_table, _formula_value, _metric_value, _page_org, _widget_org,
    compute_page_data, compute_widget_data, export_page_xlsx, list_org_alerts, preview_widget, widget_drill,
)


# --------------------------------------------------------------------------- #
# Дашборды
# --------------------------------------------------------------------------- #
async def create_dashboard(conn, org_id, user_id, name: str, description: Optional[str],
                           folder_id: Optional[str]) -> dict:
    row = await conn.fetchrow(
        "insert into dashboards(organization_id, name, description, folder_id, created_by) "
        "values($1,$2,$3,$4::uuid,$5) returning id, name, description, publication_status, created_at",
        org_id, name, description, folder_id, user_id,
    )
    return dict(row)


async def list_dashboards(conn, org_id, user: dict) -> List[dict]:
    visible = await visible_dashboard_ids(conn, org_id, user)
    if not visible:
        return []
    rows = await conn.fetch(
        "select d.id, d.name, d.description, d.publication_status, d.created_at, "
        "(select count(*) from dashboard_pages p where p.dashboard_id=d.id) as pages, "
        "(f.dashboard_id is not null) as is_favorite "
        "from dashboards d "
        "left join dashboard_favorites f on f.dashboard_id=d.id and f.user_id=$3 "
        "where d.organization_id=$1 and d.id = any($2::uuid[]) "
        "order by is_favorite desc, d.name",
        org_id, list(visible), user["id"],
    )
    return [dict(r) for r in rows]


async def set_favorite(conn, org_id, user: dict, dashboard_id: str, on: bool) -> dict:
    """Добавить/убрать дашборд из избранного (только видимый пользователю)."""
    if not await _can_view(conn, org_id, user, dashboard_id):
        raise DashboardError("Дашборд не найден")
    if on:
        await conn.execute(
            "insert into dashboard_favorites(user_id, dashboard_id) values($1,$2::uuid) "
            "on conflict do nothing", user["id"], dashboard_id)
    else:
        await conn.execute(
            "delete from dashboard_favorites where user_id=$1 and dashboard_id=$2::uuid",
            user["id"], dashboard_id)
    return {"dashboard_id": dashboard_id, "is_favorite": on}


async def get_dashboard(conn, org_id, user: dict, dashboard_id: str) -> dict:
    if not await _can_view(conn, org_id, user, dashboard_id):
        raise DashboardError("Дашборд не найден")
    d = await conn.fetchrow(
        "select id, name, description, publication_status, created_at from dashboards "
        "where id=$1::uuid and organization_id=$2", dashboard_id, org_id,
    )
    if d is None:
        raise DashboardError("Дашборд не найден")
    pages = await conn.fetch(
        "select id, name, description, position from dashboard_pages "
        "where dashboard_id=$1::uuid order by position, created_at", dashboard_id,
    )
    return {"dashboard": dict(d), "pages": [dict(p) for p in pages]}


async def _owns_dashboard(conn, org_id, dashboard_id: str) -> bool:
    return bool(await conn.fetchval(
        "select 1 from dashboards where id=$1::uuid and organization_id=$2", dashboard_id, org_id))


async def _assert_editable(conn, dashboard_id) -> None:
    """Правки контента запрещены, пока дашборд на проверке (review) — иначе
    опубликуется не то, что проверил модератор. Отзовите заявку для изменений."""
    st = await conn.fetchval("select publication_status from dashboards where id=$1::uuid", dashboard_id)
    if st == "review":
        raise DashboardError("Дашборд на проверке — правки заблокированы; отзовите заявку, чтобы изменить")


# --------------------------------------------------------------------------- #
# Страницы
# --------------------------------------------------------------------------- #
async def create_page(conn, org_id, user_id, dashboard_id: str, name: str,
                      description: Optional[str]) -> dict:
    if not await _owns_dashboard(conn, org_id, dashboard_id):
        raise DashboardError("Дашборд не найден")
    await _assert_editable(conn, dashboard_id)
    if await conn.fetchval("select 1 from dashboard_pages where dashboard_id=$1::uuid and name=$2", dashboard_id, name):
        raise DashboardError("Страница с таким именем уже есть")
    pos = await conn.fetchval(
        "select coalesce(max(position),-1)+1 from dashboard_pages where dashboard_id=$1::uuid", dashboard_id)
    row = await conn.fetchrow(
        "insert into dashboard_pages(dashboard_id, name, description, position, created_by) "
        "values($1::uuid,$2,$3,$4,$5) returning id, name, description, position",
        dashboard_id, name, description, pos, user_id,
    )
    return dict(row)


async def update_page(conn, org_id, page_id: str, name: Optional[str], description: Optional[str]) -> dict:
    p = await _page_org(conn, org_id, page_id)
    if p is None:
        raise DashboardError("Страница не найдена")
    await _assert_editable(conn, p["dashboard_id"])
    row = await conn.fetchrow(
        "update dashboard_pages set name=coalesce($2,name), description=coalesce($3,description), "
        "updated_at=now() where id=$1::uuid returning id, name, description, position",
        page_id, name, description,
    )
    return dict(row)


async def delete_page(conn, org_id, page_id: str) -> None:
    p = await _page_org(conn, org_id, page_id)
    if p is None:
        raise DashboardError("Страница не найдена")
    await _assert_editable(conn, p["dashboard_id"])
    await conn.execute("delete from dashboard_pages where id=$1::uuid", page_id)


async def list_page_widgets(conn, org_id, page_id: str, user: dict) -> dict:
    p = await _page_org(conn, org_id, page_id)
    if p is None:
        raise DashboardError("Страница не найдена")
    if not await _can_view(conn, org_id, user, str(p["dashboard_id"])):
        raise DashboardError("Страница не найдена")
    rows = await conn.fetch(
        "select id, name, widget_type, position_x, position_y, width, height, config "
        "from widgets where page_id=$1::uuid order by position_y, position_x", page_id,
    )
    return {"page_id": page_id, "widgets": [
        {**{k: w[k] for k in ("id", "name", "widget_type", "position_x", "position_y", "width", "height")},
         "config": _cfg(w)} for w in rows]}


# --------------------------------------------------------------------------- #
# Виджеты
# --------------------------------------------------------------------------- #
async def create_widget(conn, org_id, user_id, page_id: str, name: str, widget_type: str,
                        config: dict, pos: dict) -> dict:
    if widget_type not in WIDGET_TYPES:
        raise DashboardError(f"Неизвестный тип виджета: {widget_type}")
    p = await _page_org(conn, org_id, page_id)
    if p is None:
        raise DashboardError("Страница не найдена")
    await _assert_editable(conn, p["dashboard_id"])
    row = await conn.fetchrow(
        "insert into widgets(organization_id, dashboard_id, page_id, name, widget_type, "
        "position_x, position_y, width, height, config, created_by) "
        "values($1,$2,$3::uuid,$4,$5,$6,$7,$8,$9,$10::jsonb,$11) returning id",
        org_id, p["dashboard_id"], page_id, name, widget_type,
        pos.get("position_x", 0), pos.get("position_y", 0), pos.get("width", 4), pos.get("height", 3),
        json.dumps(config, ensure_ascii=False), user_id,
    )
    return {"id": str(row["id"]), "widget_type": widget_type}




async def update_widget(conn, org_id, widget_id: str, patch: dict) -> dict:
    w = await _widget_org(conn, org_id, widget_id)
    if w is None:
        raise DashboardError("Виджет не найден")
    await _assert_editable(conn, w["dashboard_id"])
    wtype = patch.get("widget_type")
    if wtype is not None and wtype not in WIDGET_TYPES:
        raise DashboardError(f"Неизвестный тип виджета: {wtype}")
    cfg = json.dumps(patch["config"], ensure_ascii=False) if "config" in patch else None
    row = await conn.fetchrow(
        "update widgets set name=coalesce($2,name), widget_type=coalesce($8,widget_type), "
        "position_x=coalesce($3,position_x), position_y=coalesce($4,position_y), "
        "width=coalesce($5,width), height=coalesce($6,height), "
        "config=coalesce($7::jsonb,config), updated_at=now() where id=$1::uuid returning id",
        widget_id, patch.get("name"), patch.get("position_x"), patch.get("position_y"),
        patch.get("width"), patch.get("height"), cfg, wtype,
    )
    await cache.delete_prefix(f"wd:{widget_id}:")  # инвалидируем кэш данных виджета
    return {"id": str(row["id"])}


async def delete_widget(conn, org_id, widget_id: str) -> None:
    w = await _widget_org(conn, org_id, widget_id)
    if w is None:
        raise DashboardError("Виджет не найден")
    await _assert_editable(conn, w["dashboard_id"])
    await conn.execute("delete from widgets where id=$1::uuid", widget_id)
    await cache.delete_prefix(f"wd:{widget_id}:")


# --------------------------------------------------------------------------- #
# Управление доступом к дашборду (гранты)
# --------------------------------------------------------------------------- #
async def grant_targets(conn, org_id) -> dict:
    """Кому можно выдать доступ: пользователи и роли организации."""
    users = await conn.fetch(
        "select id, login, full_name from users where organization_id=$1 and is_active order by login", org_id)
    roles = await conn.fetch(
        "select id, code, name from roles where organization_id=$1 order by name", org_id)
    return {
        "users": [{"id": str(u["id"]), "login": u["login"], "full_name": u["full_name"]} for u in users],
        "roles": [{"id": str(r["id"]), "code": r["code"], "name": r["name"]} for r in roles],
    }


async def list_grants(conn, org_id, dashboard_id: str) -> List[dict]:
    if not await _owns_dashboard(conn, org_id, dashboard_id):
        raise DashboardError("Дашборд не найден")
    rows = await conn.fetch(
        "select g.id, g.grantee_type, g.role_id, g.user_id, g.granted_at, "
        "r.name as role_name, r.code as role_code, u.login, u.full_name "
        "from access_grants g "
        "left join roles r on r.id=g.role_id left join users u on u.id=g.user_id "
        "where g.dashboard_id=$1::uuid and g.scope='dashboard' order by g.granted_at", dashboard_id)
    out = []
    for g in rows:
        label = (g["role_name"] or g["role_code"]) if g["grantee_type"] == "role" else (g["full_name"] or g["login"])
        out.append({"id": str(g["id"]), "grantee_type": g["grantee_type"],
                    "role_id": str(g["role_id"]) if g["role_id"] else None,
                    "user_id": str(g["user_id"]) if g["user_id"] else None,
                    "label": label, "granted_at": g["granted_at"]})
    return out


async def add_grant(conn, org_id, granted_by, dashboard_id: str, grantee_type: str,
                    role_id: Optional[str], user_id: Optional[str]) -> dict:
    if not await _owns_dashboard(conn, org_id, dashboard_id):
        raise DashboardError("Дашборд не найден")
    if grantee_type not in ("role", "user"):
        raise DashboardError("grantee_type должен быть 'role' или 'user'")
    if grantee_type == "role":
        if not role_id:
            raise DashboardError("Укажите роль")
        if not await conn.fetchval("select 1 from roles where id=$1::uuid and organization_id=$2", role_id, org_id):
            raise DashboardError("Роль не найдена")
        user_id = None
        exists = await conn.fetchval(
            "select 1 from access_grants where dashboard_id=$1::uuid and scope='dashboard' "
            "and grantee_type='role' and role_id=$2::uuid", dashboard_id, role_id)
    else:
        if not user_id:
            raise DashboardError("Укажите пользователя")
        if not await conn.fetchval("select 1 from users where id=$1::uuid and organization_id=$2", user_id, org_id):
            raise DashboardError("Пользователь не найден")
        role_id = None
        exists = await conn.fetchval(
            "select 1 from access_grants where dashboard_id=$1::uuid and scope='dashboard' "
            "and grantee_type='user' and user_id=$2::uuid", dashboard_id, user_id)
    if exists:
        raise DashboardError("Доступ уже выдан")
    row = await conn.fetchrow(
        "insert into access_grants(scope, dashboard_id, grantee_type, role_id, user_id, granted_by) "
        "values('dashboard', $1::uuid, $2, $3::uuid, $4::uuid, $5) returning id",
        dashboard_id, grantee_type, role_id, user_id, granted_by)
    await audit_svc.write_event(
        conn, org_id, granted_by, "grant_access", "dashboard", dashboard_id,
        new_data={"grant_id": str(row["id"]), "grantee_type": grantee_type,
                  "role_id": role_id, "user_id": user_id})
    return {"id": str(row["id"])}


async def remove_grant(conn, org_id, dashboard_id: str, grant_id: str, actor_user_id) -> None:
    if not await _owns_dashboard(conn, org_id, dashboard_id):
        raise DashboardError("Дашборд не найден")
    old = await conn.fetchrow(
        "select grantee_type, role_id, user_id from access_grants "
        "where id=$1::uuid and dashboard_id=$2::uuid and scope='dashboard'",
        grant_id, dashboard_id)
    if old is None:
        raise DashboardError("Грант не найден")
    await conn.execute(
        "delete from access_grants where id=$1::uuid and dashboard_id=$2::uuid and scope='dashboard'",
        grant_id, dashboard_id)
    await audit_svc.write_event(
        conn, org_id, actor_user_id, "revoke_access", "dashboard", dashboard_id,
        old_data={"grant_id": grant_id, "grantee_type": old["grantee_type"],
                  "role_id": str(old["role_id"]) if old["role_id"] else None,
                  "user_id": str(old["user_id"]) if old["user_id"] else None})


# --------------------------------------------------------------------------- #
# Пресеты фильтров дашборда (FR-13, сохранённые наборы)
# filters = {from, to, row} — период и категория/строка глобального фильтра.
# Список/применение — по праву просмотра; создание/удаление — manage.
# --------------------------------------------------------------------------- #
_PRESET_KEYS = ("from", "to", "row")


async def list_presets(conn, org_id, user: dict, dashboard_id: str) -> List[dict]:
    if not await _can_view(conn, org_id, user, dashboard_id):
        raise DashboardError("Дашборд не найден")
    rows = await conn.fetch(
        "select id, name, filters, created_at from dashboard_filter_presets "
        "where dashboard_id=$1::uuid order by name", dashboard_id)
    out = []
    for r in rows:
        f = r["filters"]
        if isinstance(f, str):
            f = json.loads(f)
        out.append({"id": str(r["id"]), "name": r["name"], "filters": f or {}})
    return out


async def create_preset(conn, org_id, user_id, dashboard_id: str, name: str, filters: dict) -> dict:
    if not await _owns_dashboard(conn, org_id, dashboard_id):
        raise DashboardError("Дашборд не найден")
    name = (name or "").strip()
    if not name:
        raise DashboardError("Укажите название пресета")
    clean = {k: filters[k] for k in _PRESET_KEYS if filters.get(k)}
    if await conn.fetchval(
            "select 1 from dashboard_filter_presets where dashboard_id=$1::uuid and name=$2", dashboard_id, name):
        raise DashboardError("Пресет с таким именем уже есть")
    row = await conn.fetchrow(
        "insert into dashboard_filter_presets(dashboard_id, name, filters, created_by) "
        "values($1::uuid,$2,$3::jsonb,$4) returning id, name",
        dashboard_id, name, json.dumps(clean, ensure_ascii=False), user_id)
    return {"id": str(row["id"]), "name": row["name"], "filters": clean}


async def delete_preset(conn, org_id, dashboard_id: str, preset_id: str) -> None:
    if not await _owns_dashboard(conn, org_id, dashboard_id):
        raise DashboardError("Дашборд не найден")
    res = await conn.execute(
        "delete from dashboard_filter_presets where id=$1::uuid and dashboard_id=$2::uuid",
        preset_id, dashboard_id)
    if res.endswith("0"):
        raise DashboardError("Пресет не найден")


# --------------------------------------------------------------------------- #
# Авто-сборка дашборда из объекта (rule-based, не ИИ)
# --------------------------------------------------------------------------- #
async def _dataset_numeric_fields(conn, org_id, dataset_code: str) -> List[dict]:
    rel = await mr._active_release(conn, org_id, dataset_code)
    if rel is None:
        return []
    rows = await conn.fetch(
        "select drf.canonical_field_code as code, coalesce(cf.name, drf.canonical_field_code) as name "
        "from dataset_release_fields drf "
        "left join canonical_fields cf on cf.code=drf.canonical_field_code "
        "  and cf.object_id=(select object_id from dataset_releases where id=$1) "
        "where drf.dataset_release_id=$1 and coalesce(cf.data_type,'text')='number' "
        "order by drf.canonical_field_code", rel)
    return [dict(r) for r in rows]


async def suggest_widgets(conn, org_id, dataset_code: str) -> List[dict]:
    """Подсказки «что собрать» под датасет: готовые спецификации виджетов
    (KPI по каждому числовому полю, график по строкам, динамика при >1 периода,
    сравнение/план-факт при ≥2 полях, таблица-первичка). Пользователь выбирает."""
    fields = await _dataset_numeric_fields(conn, org_id, dataset_code)
    if not fields:
        raise DashboardError("У датасета нет числовых полей — сначала распознайте документ")
    dsname = await conn.fetchval(
        "select max(name) from dataset_releases where organization_id=$1 and code=$2 and status<>'superseded'",
        org_id, dataset_code) or dataset_code
    periods = await conn.fetchval(
        "select count(distinct reporting_period_start) from dataset_releases "
        "where organization_id=$1 and code=$2 and status<>'superseded'", org_id, dataset_code) or 0

    specs: List[dict] = []
    for f in fields:
        specs.append({"name": f"Σ {f['name']}", "widget_type": "kpi",
                      "config": {"dataset_code": dataset_code, "value_field": f["code"]}, "width": 3, "height": 3})
    f0 = fields[0]
    specs.append({"name": f"{f0['name']} по строкам", "widget_type": "bar",
                  "config": {"dataset_code": dataset_code, "value_field": f0["code"]}, "width": 5, "height": 6})
    specs.append({"name": f"Водопад: {f0['name']}", "widget_type": "waterfall",
                  "config": {"dataset_code": dataset_code, "value_field": f0["code"]}, "width": 6, "height": 6})
    if periods > 1:
        specs.append({"name": f"Динамика: {f0['name']}", "widget_type": "dynamics",
                      "config": {"dataset_code": dataset_code, "value_field": f0["code"]}, "width": 6, "height": 6})
    if len(fields) >= 2:
        specs.append({"name": "Сравнение полей", "widget_type": "compare",
                      "config": {"dataset_code": dataset_code, "value_fields": [f["code"] for f in fields[:4]], "viz": "bar"},
                      "width": 6, "height": 7})
        specs.append({"name": "Тепловая карта", "widget_type": "heatmap",
                      "config": {"dataset_code": dataset_code, "value_fields": [f["code"] for f in fields[:6]]},
                      "width": 6, "height": 7})
        specs.append({"name": "Сводная таблица", "widget_type": "pivot",
                      "config": {"dataset_code": dataset_code, "value_fields": [f["code"] for f in fields[:6]]},
                      "width": 6, "height": 6})
        specs.append({"name": f"План/факт: {fields[0]['name']} / {fields[1]['name']}", "widget_type": "plan_fact",
                      "config": {"dataset_code": dataset_code, "plan_field": fields[0]["code"], "fact_field": fields[1]["code"]},
                      "width": 4, "height": 5})
    specs.append({"name": f"{dsname}: таблица", "widget_type": "table",
                  "config": {"dataset_code": dataset_code}, "width": 6, "height": 6})
    return specs


async def auto_build(conn, org_id, user_id, object_id: str, name=None) -> dict:
    """Собирает черновик дашборда по объекту: на каждый датасет объекта — KPI,
    столбчатый график, динамику (если >1 периода) и таблицу-первичку."""
    obj = await conn.fetchrow(
        "select id, name from objects where id=$1::uuid and organization_id=$2", object_id, org_id)
    if obj is None:
        raise DashboardError("Объект не найден")
    ds = await conn.fetch(
        "select code, max(name) as name, count(distinct reporting_period_start) as periods "
        "from dataset_releases where organization_id=$1 and object_id=$2::uuid and status<>'superseded' "
        "group by code order by max(created_at) desc", org_id, object_id)
    if not ds:
        raise DashboardError("У объекта нет выпущенных датасетов — сначала распознайте документ")

    dash = await create_dashboard(conn, org_id, user_id, name or f"Дашборд «{obj['name']}»",
                                  f"Авто-сборка по объекту «{obj['name']}»", None)
    did = str(dash["id"])
    page = await create_page(conn, org_id, user_id, did, "Обзор", None)
    pid = str(page["id"])

    n, y = 0, 0
    for d in ds:
        code, dsname = d["code"], (d["name"] or d["code"])
        fields = await _dataset_numeric_fields(conn, org_id, code)
        if not fields:
            continue
        f0 = fields[0]
        await create_widget(conn, org_id, user_id, pid, f"{dsname}: Σ {f0['name']}", "kpi",
                            {"dataset_code": code, "value_field": f0["code"]},
                            {"position_x": 0, "position_y": y, "width": 3, "height": 3}); n += 1
        await create_widget(conn, org_id, user_id, pid, f"{dsname}: {f0['name']} по строкам", "bar",
                            {"dataset_code": code, "value_field": f0["code"]},
                            {"position_x": 3, "position_y": y, "width": 5, "height": 6}); n += 1
        if (d["periods"] or 0) > 1:
            await create_widget(conn, org_id, user_id, pid, f"{dsname}: динамика {f0['name']}", "dynamics",
                                {"dataset_code": code, "value_field": f0["code"]},
                                {"position_x": 8, "position_y": y, "width": 4, "height": 6}); n += 1
        await create_widget(conn, org_id, user_id, pid, f"{dsname}: таблица", "table",
                            {"dataset_code": code},
                            {"position_x": 0, "position_y": y + 6, "width": 6, "height": 6}); n += 1
        y += 12
    return {"dashboard_id": did, "page_id": pid, "widgets": n}


# --------------------------------------------------------------------------- #
# Версии и публикация дашборда
# --------------------------------------------------------------------------- #
async def _snapshot(conn, dashboard_id: str) -> dict:
    pages = await conn.fetch(
        "select id, name, description, position from dashboard_pages "
        "where dashboard_id=$1::uuid order by position", dashboard_id)
    out = []
    for p in pages:
        ws = await conn.fetch(
            "select name, widget_type, position_x, position_y, width, height, config "
            "from widgets where page_id=$1 order by position_y, position_x", p["id"])
        out.append({"name": p["name"], "description": p["description"], "position": p["position"],
                    "widgets": [{"name": w["name"], "widget_type": w["widget_type"],
                                 "position_x": w["position_x"], "position_y": w["position_y"],
                                 "width": w["width"], "height": w["height"], "config": _cfg(w)} for w in ws]})
    return {"pages": out}


async def publish(conn, org_id, user_id, dashboard_id: str) -> dict:
    if not await _owns_dashboard(conn, org_id, dashboard_id):
        raise DashboardError("Дашборд не найден")
    snap = await _snapshot(conn, dashboard_id)
    vno = await conn.fetchval(
        "select coalesce(max(version_no),0)+1 from dashboard_versions where dashboard_id=$1::uuid", dashboard_id)
    await conn.execute(
        "insert into dashboard_versions(dashboard_id, version_no, snapshot, created_by, status_code) "
        "values($1::uuid,$2,$3::jsonb,$4,'published')", dashboard_id, vno,
        json.dumps(snap, ensure_ascii=False), user_id)
    await conn.execute(
        "update dashboards set publication_status='published', published_by=$2, published_at=now(), "
        "version_no=$3, updated_at=now() where id=$1::uuid", dashboard_id, user_id, vno)
    await audit_svc.write_event(
        conn, org_id, user_id, "publish", "dashboard", dashboard_id,
        new_data={"version_no": vno, "publication_status": "published"})
    return {"publication_status": "published", "version_no": vno}


async def unpublish(conn, org_id, dashboard_id: str) -> dict:
    if not await _owns_dashboard(conn, org_id, dashboard_id):
        raise DashboardError("Дашборд не найден")
    await conn.execute(
        "update dashboards set publication_status='draft', updated_at=now() where id=$1::uuid", dashboard_id)
    return {"publication_status": "draft"}


async def list_versions(conn, org_id, user: dict, dashboard_id: str) -> list:
    if not await _can_view(conn, org_id, user, dashboard_id):
        raise DashboardError("Дашборд не найден")
    rows = await conn.fetch(
        "select version_no, status_code, created_at from dashboard_versions "
        "where dashboard_id=$1::uuid order by version_no desc", dashboard_id)
    return [dict(r) for r in rows]


async def restore_version(conn, org_id, user_id, dashboard_id: str, version_no: int) -> dict:
    if not await _owns_dashboard(conn, org_id, dashboard_id):
        raise DashboardError("Дашборд не найден")
    snap = await conn.fetchval(
        "select snapshot from dashboard_versions where dashboard_id=$1::uuid and version_no=$2",
        dashboard_id, version_no)
    if snap is None:
        raise DashboardError("Версия не найдена")
    if isinstance(snap, str):
        snap = json.loads(snap)
    await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", dashboard_id)
    for page in snap.get("pages", []):
        p = await create_page(conn, org_id, user_id, dashboard_id, page["name"], page.get("description"))
        for w in page.get("widgets", []):
            await create_widget(conn, org_id, user_id, str(p["id"]), w["name"], w["widget_type"], w.get("config", {}),
                                {"position_x": w.get("position_x", 0), "position_y": w.get("position_y", 0),
                                 "width": w.get("width", 4), "height": w.get("height", 4)})
    return {"restored_version": version_no, "pages": len(snap.get("pages", []))}


# --------------------------------------------------------------------------- #
# Шаблоны дашбордов
# --------------------------------------------------------------------------- #
async def save_as_template(conn, org_id, user_id, dashboard_id: str, name: str, description=None) -> dict:
    if not await _owns_dashboard(conn, org_id, dashboard_id):
        raise DashboardError("Дашборд не найден")
    if await conn.fetchval("select 1 from dashboard_templates where organization_id=$1 and name=$2", org_id, name):
        raise DashboardError("Шаблон с таким именем уже есть")
    spec = await _snapshot(conn, dashboard_id)
    row = await conn.fetchrow(
        "insert into dashboard_templates(organization_id, name, description, spec, created_by) "
        "values($1,$2,$3,$4::jsonb,$5) returning id, name",
        org_id, name, description, json.dumps(spec, ensure_ascii=False), user_id)
    return {"id": str(row["id"]), "name": row["name"]}


async def list_templates(conn, org_id) -> list:
    rows = await conn.fetch(
        "select id, name, description, created_at from dashboard_templates "
        "where organization_id=$1 order by name", org_id)
    return [dict(r) for r in rows]


async def create_from_template(conn, org_id, user_id, template_id: str, name: str) -> dict:
    spec = await conn.fetchval(
        "select spec from dashboard_templates where id=$1::uuid and organization_id=$2", template_id, org_id)
    if spec is None:
        raise DashboardError("Шаблон не найден")
    if isinstance(spec, str):
        spec = json.loads(spec)
    dash = await create_dashboard(conn, org_id, user_id, name, "Создан из шаблона", None)
    did = str(dash["id"])
    for page in spec.get("pages", []):
        p = await create_page(conn, org_id, user_id, did, page["name"], page.get("description"))
        for w in page.get("widgets", []):
            await create_widget(conn, org_id, user_id, str(p["id"]), w["name"], w["widget_type"], w.get("config", {}),
                                {"position_x": w.get("position_x", 0), "position_y": w.get("position_y", 0),
                                 "width": w.get("width", 4), "height": w.get("height", 4)})
    return {"dashboard_id": did}
