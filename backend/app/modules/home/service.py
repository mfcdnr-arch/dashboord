"""Сервис «Главной»: сводка для витрины + выбор ключевых KPI.

Блоки: счётчики (обзор), каталог страниц (кликабельный), лента «что нового»,
свежесть данных по объектам, ключевые KPI (значения считаются на лету).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from ..dashboards import service as dash_svc
from ..metrics import resolver as mr
from ..metrics.parser import FormulaError


class HomeError(Exception):
    pass


async def _metric_value(conn, org_id, code: str):
    row = await conn.fetchrow(
        "select m.name, mv.formula_ast, mv.unit from metrics m "
        "join metric_versions mv on mv.metric_id=m.id "
        "where m.organization_id=$1 and m.code=$2 "
        "order by (case mv.status when 'approved' then 0 when 'validated' then 1 else 2 end), "
        "mv.version_no desc limit 1",
        org_id, code,
    )
    if row is None:
        return None, None, None
    ast = row["formula_ast"]
    if isinstance(ast, str):
        ast = json.loads(ast)
    try:
        value = await mr.evaluate_ast(conn, org_id, ast)
        return row["name"], value, row["unit"]
    except FormulaError as e:
        return row["name"], None, str(e)


async def get_home(conn, org_id, user: dict) -> dict:
    # RLS: каталог/счётчик дашбордов/алерты — только по доступным пользователю дашбордам
    visible = list(await dash_svc.visible_dashboard_ids(conn, org_id, user))

    counters = await conn.fetchrow(
        "select "
        "(select count(*) from dashboards where organization_id=$1 and id = any($2::uuid[])) as dashboards, "
        "(select count(*) from objects where organization_id=$1) as objects, "
        "(select count(*) from metrics where organization_id=$1) as metrics, "
        "(select count(distinct code) from dataset_releases where organization_id=$1 and status<>'superseded') as datasets, "
        "(select count(*) from users where organization_id=$1) as users",
        org_id, visible,
    )

    pages = await conn.fetch(
        "select d.id as dashboard_id, d.name as dashboard_name, p.id as page_id, p.name as page_name, "
        "p.description, (select count(*) from widgets w where w.page_id=p.id) as widgets "
        "from dashboards d join dashboard_pages p on p.dashboard_id=d.id "
        "where d.organization_id=$1 and d.id = any($2::uuid[]) order by d.name, p.position",
        org_id, visible,
    )

    # «Что нового» — свежие датасеты, метрики, дашборды
    recent: List[dict] = []
    for r in await conn.fetch(
        "select name, created_at from dataset_releases where organization_id=$1 and status<>'superseded' "
        "order by created_at desc limit 5", org_id):
        recent.append({"kind": "dataset", "title": f"Выпуск данных «{r['name']}»", "at": r["created_at"]})
    for r in await conn.fetch(
        "select name, created_at from metrics where organization_id=$1 order by created_at desc limit 5", org_id):
        recent.append({"kind": "metric", "title": f"Метрика «{r['name']}»", "at": r["created_at"]})
    for r in await conn.fetch(
        "select name, created_at from dashboards where organization_id=$1 order by created_at desc limit 5", org_id):
        recent.append({"kind": "dashboard", "title": f"Дашборд «{r['name']}»", "at": r["created_at"]})
    recent.sort(key=lambda x: x["at"], reverse=True)
    recent = recent[:8]

    freshness = await conn.fetch(
        "select o.name, max(r.created_at) as last_update, max(r.reporting_period_start) as last_period "
        "from objects o left join dataset_releases r on r.object_id=o.id and r.status<>'superseded' "
        "where o.organization_id=$1 group by o.id, o.name order by o.name", org_id,
    )

    kpi_rows = await conn.fetch(
        "select metric_code from home_kpis where organization_id=$1 order by position, created_at", org_id)
    key_kpis: List[dict] = []
    for k in kpi_rows:
        name, value, unit = await _metric_value(conn, org_id, k["metric_code"])
        key_kpis.append({"code": k["metric_code"], "name": name or k["metric_code"],
                         "value": value, "unit": unit if value is not None else None,
                         "error": unit if value is None else None})

    return {
        "counters": dict(counters),
        "pages": [dict(p) for p in pages],
        "recent": recent,
        "freshness": [dict(f) for f in freshness],
        "key_kpis": key_kpis,
        # сработавшие KPI-алерты по порогам виджетов (warn/danger), только по доступным
        "alerts": await dash_svc.list_org_alerts(conn, org_id, user),
    }


async def add_kpi(conn, org_id, user_id, metric_code: str) -> dict:
    m = await conn.fetchval(
        "select 1 from metrics where organization_id=$1 and code=$2", org_id, metric_code)
    if not m:
        raise HomeError("Метрика не найдена")
    if await conn.fetchval("select 1 from home_kpis where organization_id=$1 and metric_code=$2", org_id, metric_code):
        raise HomeError("Эта метрика уже на главной")
    pos = await conn.fetchval("select coalesce(max(position),-1)+1 from home_kpis where organization_id=$1", org_id)
    await conn.execute(
        "insert into home_kpis(organization_id, metric_code, position, created_by) values($1,$2,$3,$4)",
        org_id, metric_code, pos, user_id)
    return {"metric_code": metric_code}


async def remove_kpi(conn, org_id, metric_code: str) -> None:
    await conn.execute(
        "delete from home_kpis where organization_id=$1 and metric_code=$2", org_id, metric_code)
