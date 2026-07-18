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

from ..metrics import resolver as mr
from ..metrics.parser import FormulaError, extract_dependencies


class DashboardError(Exception):
    """Ошибка бизнес-логики дашбордов (в роутере → 400/404)."""


WIDGET_TYPES = {"kpi", "table", "bar", "line", "pie", "plan_fact", "dynamics", "compare"}


def _cfg(row) -> Dict[str, Any]:
    c = row["config"]
    if isinstance(c, str):
        return json.loads(c) if c else {}
    return c or {}


# --------------------------------------------------------------------------- #
# KPI-алерты + условное форматирование
# Пороги задаются в config виджета: config["alerts"] = [
#   {level: danger|warn|good, op: lt|lte|gt|gte|eq|between|outside,
#    value: number, value2?: number, label?: str}
# ]  — первое сработавшее правило определяет цвет/подпись.
# Что сравнивается (config["alert_on"]):
#   kpi        → значение (value, всегда);
#   plan_fact  → pct (по умолч.) | fact | delta | plan;
#   dynamics   → last (по умолч.) | change | change_pct.
# --------------------------------------------------------------------------- #
_ALERT_STYLES = {
    "danger": {"color": "#a32d2d", "bg": "#fcebeb"},
    "warn":   {"color": "#9a6a00", "bg": "#fff4e0"},
    "good":   {"color": "#0f6e56", "bg": "#eaf5f0"},
}
_ALERT_OP_TXT = {"lt": "<", "lte": "≤", "gt": ">", "gte": "≥", "eq": "=",
                 "between": "в диапазоне", "outside": "вне диапазона"}


def _alert_measure(widget_type: str, cfg: dict, data: dict):
    if widget_type == "kpi":
        return data.get("value")
    if widget_type == "plan_fact":
        return data.get(cfg.get("alert_on") or "pct")
    if widget_type == "dynamics":
        key = cfg.get("alert_on") or "last"
        if key == "last":
            vals = data.get("values") or []
            return vals[-1] if vals else None
        return data.get(key)  # change | change_pct
    return None


def _alert_match(measure, rule: dict) -> bool:
    if measure is None:
        return False
    op = rule.get("op")
    try:
        m = float(measure)
        v = float(rule["value"]) if rule.get("value") is not None else None
        v2 = float(rule["value2"]) if rule.get("value2") is not None else None
    except (TypeError, ValueError, KeyError):
        return False
    if op == "lt":      return v is not None and m < v
    if op == "lte":     return v is not None and m <= v
    if op == "gt":      return v is not None and m > v
    if op == "gte":     return v is not None and m >= v
    if op == "eq":      return v is not None and m == v
    if op == "between": return v is not None and v2 is not None and v <= m <= v2
    if op == "outside": return v is not None and v2 is not None and (m < v or m > v2)
    return False


def evaluate_alert(widget_type: str, cfg: dict, data: dict) -> Optional[dict]:
    rules = cfg.get("alerts") or []
    if not rules:
        return None
    measure = _alert_measure(widget_type, cfg, data)
    for rule in rules:
        if _alert_match(measure, rule):
            lvl = rule.get("level", "danger")
            st = _ALERT_STYLES.get(lvl, _ALERT_STYLES["danger"])
            label = rule.get("label")
            if not label:
                op = _ALERT_OP_TXT.get(rule.get("op"), rule.get("op"))
                if rule.get("op") in ("between", "outside"):
                    label = f"{op} {rule.get('value')}…{rule.get('value2')}"
                else:
                    label = f"{op} {rule.get('value')}"
            return {"level": lvl, "color": st["color"], "bg": st["bg"],
                    "label": label, "measure": measure}
    return None


# --------------------------------------------------------------------------- #
# RLS: разграничение доступа к дашбордам (через существующий ACL access_grants)
# Привилегированные роли видят все дашборды организации; остальные — только
# созданные ими самими или те, на которые есть грант scope='dashboard'
# (напрямую на пользователя или на одну из его ролей). Виджеты/данные/алерты
# наследуют видимость дашборда.
# --------------------------------------------------------------------------- #
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
        rows = await conn.fetch(
            "select distinct d.id from dashboards d "
            "left join access_grants g on g.dashboard_id=d.id and g.scope='dashboard' "
            "  and ((g.grantee_type='user' and g.user_id=$2) "
            "       or (g.grantee_type='role' and g.role_id = any($3::uuid[]))) "
            "where d.organization_id=$1 and (d.created_by=$2 or g.id is not null)",
            org_id, user["id"], ctx["role_ids"])
    return {str(r["id"]) for r in rows}


async def _can_view(conn, org_id, user: dict, dashboard_id: str) -> bool:
    ctx = await _user_ctx(conn, user)
    if ctx["privileged"]:
        return bool(await conn.fetchval(
            "select 1 from dashboards where id=$1::uuid and organization_id=$2", dashboard_id, org_id))
    return bool(await conn.fetchval(
        "select 1 from dashboards d where d.id=$1::uuid and d.organization_id=$2 and ("
        "d.created_by=$3 or exists(select 1 from access_grants g where g.dashboard_id=d.id "
        "and g.scope='dashboard' and ((g.grantee_type='user' and g.user_id=$3) "
        "or (g.grantee_type='role' and g.role_id = any($4::uuid[])))))",
        dashboard_id, org_id, user["id"], ctx["role_ids"]))


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
        "(select count(*) from dashboard_pages p where p.dashboard_id=d.id) as pages "
        "from dashboards d where d.organization_id=$1 and d.id = any($2::uuid[]) order by d.name",
        org_id, list(visible),
    )
    return [dict(r) for r in rows]


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


# --------------------------------------------------------------------------- #
# Страницы
# --------------------------------------------------------------------------- #
async def create_page(conn, org_id, user_id, dashboard_id: str, name: str,
                      description: Optional[str]) -> dict:
    if not await _owns_dashboard(conn, org_id, dashboard_id):
        raise DashboardError("Дашборд не найден")
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


async def _page_org(conn, org_id, page_id: str):
    return await conn.fetchrow(
        "select p.id, p.dashboard_id from dashboard_pages p join dashboards d on d.id=p.dashboard_id "
        "where p.id=$1::uuid and d.organization_id=$2", page_id, org_id)


async def update_page(conn, org_id, page_id: str, name: Optional[str], description: Optional[str]) -> dict:
    p = await _page_org(conn, org_id, page_id)
    if p is None:
        raise DashboardError("Страница не найдена")
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
    row = await conn.fetchrow(
        "insert into widgets(organization_id, dashboard_id, page_id, name, widget_type, "
        "position_x, position_y, width, height, config, created_by) "
        "values($1,$2,$3::uuid,$4,$5,$6,$7,$8,$9,$10::jsonb,$11) returning id",
        org_id, p["dashboard_id"], page_id, name, widget_type,
        pos.get("position_x", 0), pos.get("position_y", 0), pos.get("width", 4), pos.get("height", 3),
        json.dumps(config, ensure_ascii=False), user_id,
    )
    return {"id": str(row["id"]), "widget_type": widget_type}


async def _widget_org(conn, org_id, widget_id: str):
    return await conn.fetchrow(
        "select w.* from widgets w where w.id=$1::uuid and w.organization_id=$2", widget_id, org_id)


async def update_widget(conn, org_id, widget_id: str, patch: dict) -> dict:
    w = await _widget_org(conn, org_id, widget_id)
    if w is None:
        raise DashboardError("Виджет не найден")
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
    return {"id": str(row["id"])}


async def delete_widget(conn, org_id, widget_id: str) -> None:
    w = await _widget_org(conn, org_id, widget_id)
    if w is None:
        raise DashboardError("Виджет не найден")
    await conn.execute("delete from widgets where id=$1::uuid", widget_id)


# --------------------------------------------------------------------------- #
# Вычисление данных виджета
# --------------------------------------------------------------------------- #
async def _best_metric_version(conn, org_id, code: str):
    # приоритет версии: одобренная → проверенная → любая (черновик не берётся вперёд проверенной)
    return await conn.fetchrow(
        "select m.name, mv.formula_expression, mv.formula_ast, mv.unit, mv.version_no, mv.status "
        "from metrics m join metric_versions mv on mv.metric_id=m.id "
        "where m.organization_id=$1 and m.code=$2 "
        "order by (case mv.status when 'approved' then 0 when 'validated' then 1 else 2 end), "
        "mv.version_no desc limit 1",
        org_id, code,
    )


async def _metric_value(conn, org_id, code: str):
    row = await _best_metric_version(conn, org_id, code)
    if row is None:
        raise DashboardError(f"Метрика '{code}' не найдена")
    ast = row["formula_ast"]
    if isinstance(ast, str):
        ast = json.loads(ast)
    try:
        value = await mr.evaluate_ast(conn, org_id, ast)
    except FormulaError as e:
        raise DashboardError(str(e))
    return value, row["unit"]


async def _dataset_series(conn, org_id, dataset_code: str, value_field: str, row=None):
    rel = await mr._active_release(conn, org_id, dataset_code)
    if rel is None:
        raise DashboardError(f"Датасет '{dataset_code}' не найден или не выпущен")
    rows = await conn.fetch(
        "select row_label, value_number from dataset_values "
        "where dataset_release_id=$1 and canonical_field_code=$2 and value_number is not null "
        "and ($3::text is null or row_label=$3) order by row_index", rel, value_field, row,
    )
    return [{"category": r["row_label"], "value": float(r["value_number"])} for r in rows]


async def _dataset_multi_series(conn, org_id, dataset_code: str, value_fields: List[str], row=None) -> dict:
    """Несколько серий по одному датасету: категории=строки, серия=каждое поле."""
    rel = await mr._active_release(conn, org_id, dataset_code)
    if rel is None:
        raise DashboardError(f"Датасет '{dataset_code}' не найден или не выпущен")
    names = {r["code"]: r["name"] for r in await conn.fetch(
        "select drf.canonical_field_code as code, coalesce(cf.name, drf.canonical_field_code) as name "
        "from dataset_release_fields drf "
        "left join canonical_fields cf on cf.code=drf.canonical_field_code "
        "  and cf.object_id=(select object_id from dataset_releases where id=$1) "
        "where drf.dataset_release_id=$1", rel)}
    rows = await conn.fetch(
        "select row_index, row_label, canonical_field_code, value_number from dataset_values "
        "where dataset_release_id=$1 and canonical_field_code = any($2::text[]) and value_number is not null "
        "and ($3::text is null or row_label=$3) order by row_index", rel, value_fields, row)
    categories: List[str] = []
    per: Dict[str, Dict[str, float]] = {f: {} for f in value_fields}
    for r in rows:
        lbl = r["row_label"]
        if lbl not in categories:
            categories.append(lbl)
        per[r["canonical_field_code"]][lbl] = float(r["value_number"])
    series = [{"name": names.get(f, f), "data": [per[f].get(l) for l in categories]} for f in value_fields]
    return {"categories": categories, "series": series}


async def _dataset_period_series(conn, org_id, dataset_code: str, value_field: str,
                                from_date=None, to_date=None, row=None):
    """Ряд по периодам: для каждого активного выпуска датасета — сумма поля (динамика)."""
    rels = await conn.fetch(
        "select id, reporting_period_start from dataset_releases "
        "where organization_id=$1 and code=$2 and status <> 'superseded' "
        "and ($3::text is null or reporting_period_start >= $3::text::date) "
        "and ($4::text is null or reporting_period_start <= $4::text::date) "
        "order by reporting_period_start nulls last",
        org_id, dataset_code, from_date, to_date,
    )
    if not rels:
        raise DashboardError(f"Датасет '{dataset_code}' не найден или не выпущен")
    out = []
    for r in rels:
        s = await conn.fetchval(
            "select coalesce(sum(value_number),0) from dataset_values "
            "where dataset_release_id=$1 and canonical_field_code=$2 and ($3::text is null or row_label=$3)",
            r["id"], value_field, row)
        period = r["reporting_period_start"].isoformat() if r["reporting_period_start"] else "—"
        out.append((period, float(s)))
    return out


async def _dataset_table(conn, org_id, dataset_code: str, row=None):
    rel = await mr._active_release(conn, org_id, dataset_code)
    if rel is None:
        raise DashboardError(f"Датасет '{dataset_code}' не найден или не выпущен")
    fields = await conn.fetch(
        "select distinct canonical_field_code from dataset_values where dataset_release_id=$1 "
        "order by canonical_field_code", rel)
    cols = [f["canonical_field_code"] for f in fields]
    vals = await conn.fetch(
        "select row_index, row_label, canonical_field_code, value_text, value_number "
        "from dataset_values where dataset_release_id=$1 and ($2::text is null or row_label=$2) "
        "order by row_index", rel, row)
    by_row: Dict[int, dict] = {}
    for v in vals:
        r = by_row.setdefault(v["row_index"], {"__row__": v["row_label"]})
        r[v["canonical_field_code"]] = (
            float(v["value_number"]) if v["value_number"] is not None else v["value_text"])
    rows = [{"row": by_row[i].get("__row__"), **{c: by_row[i].get(c) for c in cols}}
            for i in sorted(by_row)]
    return {"columns": cols, "rows": rows}


async def compute_widget_data(conn, org_id, widget_id: str, from_date=None, to_date=None, row=None, user: dict = None) -> dict:
    w = await _widget_org(conn, org_id, widget_id)
    if w is None:
        raise DashboardError("Виджет не найден")
    if user is not None and not await _can_view(conn, org_id, user, str(w["dashboard_id"])):
        raise DashboardError("Виджет не найден")
    t = w["widget_type"]
    cfg = _cfg(w)

    if t == "compare":
        fields = cfg.get("value_fields") or []
        if not cfg.get("dataset_code") or not fields:
            raise DashboardError("Сравнение: укажите dataset_code и value_fields")
        res = await _dataset_multi_series(conn, org_id, cfg["dataset_code"], fields, row)
        res["type"], res["viz"], res["title"] = "compare", cfg.get("viz", "bar"), w["name"]
        return res

    if t == "dynamics":
        if not cfg.get("dataset_code") or not cfg.get("value_field"):
            raise DashboardError("Динамика: укажите dataset_code и value_field")
        series = await _dataset_period_series(conn, org_id, cfg["dataset_code"], cfg["value_field"], from_date, to_date, row)
        periods = [p for p, _ in series]
        values = [v for _, v in series]
        change = values[-1] - values[-2] if len(values) >= 2 else None
        change_pct = (change / values[-2] * 100.0) if (change is not None and values[-2]) else None
        res = {"type": "dynamics", "title": w["name"], "periods": periods, "values": values,
               "change": change, "change_pct": change_pct}
        res["alert"] = evaluate_alert("dynamics", cfg, res)
        return res

    if t == "kpi":
        if cfg.get("metric_code"):
            value, unit = await _metric_value(conn, org_id, cfg["metric_code"])
        elif cfg.get("dataset_code") and cfg.get("value_field"):
            series = await _dataset_series(conn, org_id, cfg["dataset_code"], cfg["value_field"], row)
            value, unit = sum(s["value"] for s in series), cfg.get("unit")
        else:
            raise DashboardError("KPI: укажите metric_code или dataset_code+value_field")
        res = {"type": "kpi", "value": value, "unit": unit, "title": w["name"]}
        res["alert"] = evaluate_alert("kpi", cfg, res)
        return res

    if t == "plan_fact":
        if cfg.get("plan_metric") and cfg.get("fact_metric"):
            plan, unit = await _metric_value(conn, org_id, cfg["plan_metric"])
            fact, _ = await _metric_value(conn, org_id, cfg["fact_metric"])
        elif cfg.get("dataset_code") and cfg.get("plan_field") and cfg.get("fact_field"):
            plan = sum(s["value"] for s in await _dataset_series(conn, org_id, cfg["dataset_code"], cfg["plan_field"], row))
            fact = sum(s["value"] for s in await _dataset_series(conn, org_id, cfg["dataset_code"], cfg["fact_field"], row))
            unit = cfg.get("unit")
        else:
            raise DashboardError("План-факт: укажите plan_metric+fact_metric или dataset_code+plan_field+fact_field")
        pct = (fact / plan * 100.0) if plan else None
        res = {"type": "plan_fact", "plan": plan, "fact": fact, "delta": fact - plan, "pct": pct, "unit": unit, "title": w["name"]}
        res["alert"] = evaluate_alert("plan_fact", cfg, res)
        return res

    if t == "table":
        if not cfg.get("dataset_code"):
            raise DashboardError("Таблица: укажите dataset_code")
        table = await _dataset_table(conn, org_id, cfg["dataset_code"], row)
        return {"type": "table", "title": w["name"], **table}

    # bar | line | pie
    if not cfg.get("dataset_code") or not cfg.get("value_field"):
        raise DashboardError("График: укажите dataset_code и value_field")
    series = await _dataset_series(conn, org_id, cfg["dataset_code"], cfg["value_field"], row)
    return {"type": t, "title": w["name"],
            "categories": [s["category"] for s in series],
            "values": [s["value"] for s in series]}


async def list_org_alerts(conn, org_id, user: dict, limit: int = 30) -> List[dict]:
    """Сработавшие KPI-алерты по доступным пользователю дашбордам — для «Главной».
    Возвращаются только уровни warn/danger (good — позитивная подсветка, не тревога)."""
    visible = await visible_dashboard_ids(conn, org_id, user)
    if not visible:
        return []
    rows = await conn.fetch(
        "select w.id, w.name, w.widget_type, w.dashboard_id, "
        "d.name as dashboard_name, d.publication_status, "
        "(select p.name from dashboard_pages p where p.id=w.page_id) as page_name "
        "from widgets w join dashboards d on d.id=w.dashboard_id "
        "where w.organization_id=$1 and w.dashboard_id = any($2::uuid[]) "
        "and (w.config ->> 'alerts') is not null "
        "order by d.name", org_id, list(visible),
    )
    out: List[dict] = []
    for w in rows:
        try:
            data = await compute_widget_data(conn, org_id, str(w["id"]))
        except DashboardError:
            continue
        al = data.get("alert")
        if not al or al["level"] not in ("warn", "danger"):
            continue
        out.append({
            "widget_id": str(w["id"]), "widget_name": w["name"], "widget_type": w["widget_type"],
            "dashboard_id": str(w["dashboard_id"]), "dashboard_name": w["dashboard_name"],
            "page_name": w["page_name"], "published": w["publication_status"] == "published",
            "level": al["level"], "label": al["label"], "measure": al["measure"], "unit": data.get("unit"),
        })
    out.sort(key=lambda x: (0 if x["level"] == "danger" else 1, x["dashboard_name"]))
    return out[:limit]


async def widget_drill(conn, org_id, widget_id: str, user: dict) -> dict:
    """Прозрачность показателя: из чего собран виджет — формулы метрик (уровень 1)
    и первичные строки датасетов (уровень 2)."""
    w = await _widget_org(conn, org_id, widget_id)
    if w is None:
        raise DashboardError("Виджет не найден")
    if not await _can_view(conn, org_id, user, str(w["dashboard_id"])):
        raise DashboardError("Виджет не найден")
    cfg = _cfg(w)
    metric_codes = [cfg[k] for k in ("metric_code", "plan_metric", "fact_metric") if cfg.get(k)]
    dataset_codes = [cfg["dataset_code"]] if cfg.get("dataset_code") else []

    metrics_info: List[dict] = []
    for code in metric_codes:
        row = await _best_metric_version(conn, org_id, code)
        if row is None:
            continue
        ast = row["formula_ast"]
        if isinstance(ast, str):
            ast = json.loads(ast)
        deps = extract_dependencies(ast)
        metrics_info.append({
            "code": code, "name": row["name"], "formula": row["formula_expression"],
            "status": row["status"], "version_no": row["version_no"], "datasets": deps["datasets"],
        })
        dataset_codes += deps["datasets"]

    seen: List[str] = []
    for dc in dataset_codes:
        if dc not in seen:
            seen.append(dc)
    tables: Dict[str, Any] = {}
    for dc in seen:
        try:
            tables[dc] = await _dataset_table(conn, org_id, dc)
        except DashboardError:
            tables[dc] = {"columns": [], "rows": []}

    return {"widget": w["name"], "widget_type": w["widget_type"],
            "metrics": metrics_info, "datasets": seen, "tables": tables}


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
    return {"id": str(row["id"])}


async def remove_grant(conn, org_id, dashboard_id: str, grant_id: str) -> None:
    if not await _owns_dashboard(conn, org_id, dashboard_id):
        raise DashboardError("Дашборд не найден")
    res = await conn.execute(
        "delete from access_grants where id=$1::uuid and dashboard_id=$2::uuid and scope='dashboard'",
        grant_id, dashboard_id)
    if res.endswith("0"):
        raise DashboardError("Грант не найден")


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
