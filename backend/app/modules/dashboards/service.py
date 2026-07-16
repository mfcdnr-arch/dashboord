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


async def list_dashboards(conn, org_id) -> List[dict]:
    rows = await conn.fetch(
        "select d.id, d.name, d.description, d.publication_status, d.created_at, "
        "(select count(*) from dashboard_pages p where p.dashboard_id=d.id) as pages "
        "from dashboards d where d.organization_id=$1 order by d.name",
        org_id,
    )
    return [dict(r) for r in rows]


async def get_dashboard(conn, org_id, dashboard_id: str) -> dict:
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


async def list_page_widgets(conn, org_id, page_id: str) -> dict:
    p = await _page_org(conn, org_id, page_id)
    if p is None:
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
    cfg = json.dumps(patch["config"], ensure_ascii=False) if "config" in patch else None
    row = await conn.fetchrow(
        "update widgets set name=coalesce($2,name), "
        "position_x=coalesce($3,position_x), position_y=coalesce($4,position_y), "
        "width=coalesce($5,width), height=coalesce($6,height), "
        "config=coalesce($7::jsonb,config), updated_at=now() where id=$1::uuid returning id",
        widget_id, patch.get("name"), patch.get("position_x"), patch.get("position_y"),
        patch.get("width"), patch.get("height"), cfg,
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


async def _dataset_series(conn, org_id, dataset_code: str, value_field: str):
    rel = await mr._active_release(conn, org_id, dataset_code)
    if rel is None:
        raise DashboardError(f"Датасет '{dataset_code}' не найден или не выпущен")
    rows = await conn.fetch(
        "select row_label, value_number from dataset_values "
        "where dataset_release_id=$1 and canonical_field_code=$2 and value_number is not null "
        "order by row_index", rel, value_field,
    )
    return [{"category": r["row_label"], "value": float(r["value_number"])} for r in rows]


async def _dataset_multi_series(conn, org_id, dataset_code: str, value_fields: List[str]) -> dict:
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
        "order by row_index", rel, value_fields)
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
                                from_date=None, to_date=None):
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
            "where dataset_release_id=$1 and canonical_field_code=$2", r["id"], value_field)
        period = r["reporting_period_start"].isoformat() if r["reporting_period_start"] else "—"
        out.append((period, float(s)))
    return out


async def _dataset_table(conn, org_id, dataset_code: str):
    rel = await mr._active_release(conn, org_id, dataset_code)
    if rel is None:
        raise DashboardError(f"Датасет '{dataset_code}' не найден или не выпущен")
    fields = await conn.fetch(
        "select distinct canonical_field_code from dataset_values where dataset_release_id=$1 "
        "order by canonical_field_code", rel)
    cols = [f["canonical_field_code"] for f in fields]
    vals = await conn.fetch(
        "select row_index, row_label, canonical_field_code, value_text, value_number "
        "from dataset_values where dataset_release_id=$1 order by row_index", rel)
    by_row: Dict[int, dict] = {}
    for v in vals:
        r = by_row.setdefault(v["row_index"], {"__row__": v["row_label"]})
        r[v["canonical_field_code"]] = (
            float(v["value_number"]) if v["value_number"] is not None else v["value_text"])
    rows = [{"row": by_row[i].get("__row__"), **{c: by_row[i].get(c) for c in cols}}
            for i in sorted(by_row)]
    return {"columns": cols, "rows": rows}


async def compute_widget_data(conn, org_id, widget_id: str, from_date=None, to_date=None) -> dict:
    w = await _widget_org(conn, org_id, widget_id)
    if w is None:
        raise DashboardError("Виджет не найден")
    t = w["widget_type"]
    cfg = _cfg(w)

    if t == "compare":
        fields = cfg.get("value_fields") or []
        if not cfg.get("dataset_code") or not fields:
            raise DashboardError("Сравнение: укажите dataset_code и value_fields")
        res = await _dataset_multi_series(conn, org_id, cfg["dataset_code"], fields)
        res["type"], res["viz"], res["title"] = "compare", cfg.get("viz", "bar"), w["name"]
        return res

    if t == "dynamics":
        if not cfg.get("dataset_code") or not cfg.get("value_field"):
            raise DashboardError("Динамика: укажите dataset_code и value_field")
        series = await _dataset_period_series(conn, org_id, cfg["dataset_code"], cfg["value_field"], from_date, to_date)
        periods = [p for p, _ in series]
        values = [v for _, v in series]
        change = values[-1] - values[-2] if len(values) >= 2 else None
        change_pct = (change / values[-2] * 100.0) if (change is not None and values[-2]) else None
        return {"type": "dynamics", "title": w["name"], "periods": periods, "values": values,
                "change": change, "change_pct": change_pct}

    if t == "kpi":
        if cfg.get("metric_code"):
            value, unit = await _metric_value(conn, org_id, cfg["metric_code"])
        elif cfg.get("dataset_code") and cfg.get("value_field"):
            series = await _dataset_series(conn, org_id, cfg["dataset_code"], cfg["value_field"])
            value, unit = sum(s["value"] for s in series), cfg.get("unit")
        else:
            raise DashboardError("KPI: укажите metric_code или dataset_code+value_field")
        return {"type": "kpi", "value": value, "unit": unit, "title": w["name"]}

    if t == "plan_fact":
        if cfg.get("plan_metric") and cfg.get("fact_metric"):
            plan, unit = await _metric_value(conn, org_id, cfg["plan_metric"])
            fact, _ = await _metric_value(conn, org_id, cfg["fact_metric"])
        elif cfg.get("dataset_code") and cfg.get("plan_field") and cfg.get("fact_field"):
            plan = sum(s["value"] for s in await _dataset_series(conn, org_id, cfg["dataset_code"], cfg["plan_field"]))
            fact = sum(s["value"] for s in await _dataset_series(conn, org_id, cfg["dataset_code"], cfg["fact_field"]))
            unit = cfg.get("unit")
        else:
            raise DashboardError("План-факт: укажите plan_metric+fact_metric или dataset_code+plan_field+fact_field")
        pct = (fact / plan * 100.0) if plan else None
        return {"type": "plan_fact", "plan": plan, "fact": fact, "delta": fact - plan, "pct": pct, "unit": unit, "title": w["name"]}

    if t == "table":
        if not cfg.get("dataset_code"):
            raise DashboardError("Таблица: укажите dataset_code")
        table = await _dataset_table(conn, org_id, cfg["dataset_code"])
        return {"type": "table", "title": w["name"], **table}

    # bar | line | pie
    if not cfg.get("dataset_code") or not cfg.get("value_field"):
        raise DashboardError("График: укажите dataset_code и value_field")
    series = await _dataset_series(conn, org_id, cfg["dataset_code"], cfg["value_field"])
    return {"type": t, "title": w["name"],
            "categories": [s["category"] for s in series],
            "values": [s["value"] for s in series]}


async def widget_drill(conn, org_id, widget_id: str) -> dict:
    """Прозрачность показателя: из чего собран виджет — формулы метрик (уровень 1)
    и первичные строки датасетов (уровень 2)."""
    w = await _widget_org(conn, org_id, widget_id)
    if w is None:
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
                            {"position_x": 0, "position_y": y, "width": 3, "height": 2}); n += 1
        await create_widget(conn, org_id, user_id, pid, f"{dsname}: {f0['name']} по строкам", "bar",
                            {"dataset_code": code, "value_field": f0["code"]},
                            {"position_x": 3, "position_y": y, "width": 5, "height": 4}); n += 1
        if (d["periods"] or 0) > 1:
            await create_widget(conn, org_id, user_id, pid, f"{dsname}: динамика {f0['name']}", "dynamics",
                                {"dataset_code": code, "value_field": f0["code"]},
                                {"position_x": 8, "position_y": y, "width": 4, "height": 4}); n += 1
        await create_widget(conn, org_id, user_id, pid, f"{dsname}: таблица", "table",
                            {"dataset_code": code},
                            {"position_x": 0, "position_y": y + 4, "width": 6, "height": 4}); n += 1
        y += 8
    return {"dashboard_id": did, "page_id": pid, "widgets": n}
