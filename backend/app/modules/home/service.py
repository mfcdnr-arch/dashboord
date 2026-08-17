"""Сервис «Главной»: сводка для витрины + выбор ключевых KPI.

Блоки: счётчики (обзор), каталог страниц (кликабельный), лента «что нового»,
свежесть данных по объектам, ключевые KPI (значения считаются на лету).
"""
from __future__ import annotations

import json
from typing import List

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
        "(select count(*) from users where organization_id=$1) as users, "
        # Документы и охваченные периоды: до появления первого дашборда это
        # единственное, что показывает, живёт система или пуста.
        "(select count(*) from documents where organization_id=$1) as documents, "
        "(select count(*) from dataset_releases where organization_id=$1 and status<>'superseded') as releases",
        org_id, visible,
    )

    # За какой период вообще есть данные и когда была последняя загрузка.
    span = await conn.fetchrow(
        "select min(reporting_period_start) as first_period, max(reporting_period_start) as last_period, "
        "       max(created_at) as last_upload "
        "from dataset_releases where organization_id=$1 and status<>'superseded'", org_id)

    # Путь настройки: какие шаги уже пройдены. Пока система не наполнена,
    # «Главная» состоит из пустых блоков и не подсказывает, что делать дальше.
    pending_review = await conn.fetchval(
        "select count(*) from publication_requests pr join dashboards d on d.id = pr.dashboard_id "
        "where d.organization_id=$1 and pr.status='pending_moderation'", org_id) or 0
    published = await conn.fetchval(
        "select count(*) from dashboards where organization_id=$1 and publication_status='published'", org_id) or 0
    setup = {
        "objects": counters["objects"] > 0,
        "documents": counters["documents"] > 0,
        "datasets": counters["datasets"] > 0,
        "metrics": counters["metrics"] > 0,
        "dashboards": counters["dashboards"] > 0,
        "published": published > 0,
    }

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

    # Что именно поступило: не «выпуск данных такой-то», а отчёт за такую-то
    # дату из такого-то файла и сколько в нём показателей. Общая лента «что
    # нового» отвечает «когда», а этот блок — «что пришло и полное ли оно».
    recent_data = [dict(r) for r in await conn.fetch(
        "select r.id, r.name, r.code, r.reporting_period_start as period, r.created_at, "
        "  ob.name as object_name, fo.name as folder_name, d.original_filename, "
        "  (select count(*) from dataset_values v where v.dataset_release_id=r.id) as values_count, "
        "  (select count(distinct v.canonical_field_code) from dataset_values v "
        "     where v.dataset_release_id=r.id) as fields_count "
        "from dataset_releases r "
        "left join objects ob on ob.id=r.object_id "
        "left join document_versions dv on dv.id=r.source_document_version_id "
        "left join documents d on d.id=dv.document_id "
        "left join folders fo on fo.id=d.folder_id "
        "where r.organization_id=$1 and r.status<>'superseded' "
        "order by r.created_at desc limit 5", org_id)]

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
        "data_span": {
            "first_period": span["first_period"] if span else None,
            "last_period": span["last_period"] if span else None,
            "last_upload": span["last_upload"] if span else None,
        },
        "recent_data": [{
            "id": str(r["id"]), "name": r["name"], "code": r["code"],
            "period": r["period"].isoformat() if r["period"] else None,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "object_name": r["object_name"], "folder_name": r["folder_name"],
            "filename": r["original_filename"],
            "values_count": r["values_count"], "fields_count": r["fields_count"],
        } for r in recent_data],
        "setup": setup,
        "pending_review": pending_review,
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
