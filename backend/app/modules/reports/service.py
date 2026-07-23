"""Сервис отчётов.

Системный мониторинг (Q5): CPU/RAM/диск через psutil + статусы сервисов
(PostgreSQL/Redis/MinIO) + размер БД, с уровнями-порогами (good/warn/danger).
Посещаемость: агрегаты по login_events (входы/неудачи/активные, по дням, топ).
Сбор локальный, on-prem, без внешних SaaS.
"""
from __future__ import annotations

import json
import time

import psutil

from ...config import settings
from ..dashboards import service as dash_svc
from ..documents import storage
from ..metrics import resolver as mr
from ..metrics.parser import FormulaError


def _level(pct: float, warn: float, crit: float) -> str:
    return "danger" if pct >= crit else ("warn" if pct >= warn else "good")


async def system_health(conn) -> dict:
    cpu = psutil.cpu_percent(interval=0.3)
    vm = psutil.virtual_memory()
    du = psutil.disk_usage("/")
    try:
        load = list(psutil.getloadavg())
    except (AttributeError, OSError):
        load = None
    uptime_sec = int(time.time() - psutil.boot_time())

    services = []
    try:
        pg_ok = (await conn.fetchval("select 1")) == 1
    except Exception:
        pg_ok = False
    db_size = None
    if pg_ok:
        try:
            db_size = await conn.fetchval("select pg_database_size(current_database())")
        except Exception:
            db_size = None
    services.append({"name": "PostgreSQL", "ok": pg_ok})

    redis_ok = False
    try:
        import redis.asyncio as aioredis
        r = aioredis.Redis(host=settings.redis_host, port=settings.redis_port, socket_connect_timeout=1)
        redis_ok = bool(await r.ping())
        await r.aclose()
    except Exception:
        redis_ok = False
    services.append({"name": "Redis", "ok": redis_ok})

    minio_ok = False
    try:
        minio_ok = bool(storage.get_client().bucket_exists(settings.minio_bucket))
    except Exception:
        minio_ok = False
    services.append({"name": "MinIO", "ok": minio_ok})

    return {
        "cpu": {"percent": round(cpu, 1), "level": _level(cpu, 70, 90)},
        "memory": {"percent": round(vm.percent, 1), "used": vm.used, "total": vm.total, "level": _level(vm.percent, 80, 92)},
        "disk": {"percent": round(du.percent, 1), "used": du.used, "total": du.total, "level": _level(du.percent, 80, 92)},
        "load": load, "cores": psutil.cpu_count(), "uptime_sec": uptime_sec,
        "db_size": db_size, "services": services,
    }


async def _eval_best_metric(conn, org_id, formula_ast):
    ast = json.loads(formula_ast) if isinstance(formula_ast, str) else formula_ast
    try:
        return await mr.evaluate_ast(conn, org_id, ast), None
    except FormulaError as e:
        return None, str(e)


async def data_quality(conn, org_id) -> dict:
    """Качество данных: свежесть по объектам (последний период/выпуск, число
    датасетов), объекты без данных, ошибки расчёта метрик."""
    objects = await conn.fetch(
        "select o.name, "
        "count(distinct r.code) filter (where r.status<>'superseded') as datasets, "
        "max(r.reporting_period_start) as last_period, max(r.created_at) as last_update "
        "from objects o left join dataset_releases r on r.object_id=o.id "
        "where o.organization_id=$1 group by o.id, o.name order by o.name", org_id)
    metrics = await conn.fetch(
        "select m.code, m.name, mv.formula_ast "
        "from metrics m join lateral ("
        "  select formula_ast from metric_versions where metric_id=m.id "
        "  order by (case status when 'approved' then 0 when 'validated' then 1 else 2 end), version_no desc limit 1"
        ") mv on true where m.organization_id=$1 order by m.name", org_id)
    metric_errors = []
    for m in metrics:
        _, err = await _eval_best_metric(conn, org_id, m["formula_ast"])
        if err:
            metric_errors.append({"code": m["code"], "name": m["name"], "error": err})
    objs = [{
        "name": o["name"], "datasets": o["datasets"],
        "last_period": o["last_period"].isoformat() if o["last_period"] else None,
        "last_update": o["last_update"].isoformat() if o["last_update"] else None,
        "status": "нет данных" if not o["datasets"] else "ок",
    } for o in objects]
    return {
        "objects": objs,
        "no_data": [o["name"] for o in objs if o["datasets"] == 0],
        "metric_errors": metric_errors,
        "metrics_total": len(metrics),
    }


async def business(conn, org_id, user: dict) -> dict:
    """Бизнес-сводка: метрики с текущими значениями + сработавшие KPI-алерты."""
    rows = await conn.fetch(
        "select m.code, m.name, mv.formula_ast, mv.unit "
        "from metrics m join lateral ("
        "  select formula_ast, unit from metric_versions where metric_id=m.id "
        "  order by (case status when 'approved' then 0 when 'validated' then 1 else 2 end), version_no desc limit 1"
        ") mv on true where m.organization_id=$1 order by m.name", org_id)
    metrics = []
    for m in rows:
        val, err = await _eval_best_metric(conn, org_id, m["formula_ast"])
        metrics.append({"code": m["code"], "name": m["name"], "unit": m["unit"] if val is not None else None,
                        "value": val, "error": err})
    alerts = await dash_svc.list_org_alerts(conn, org_id, user)
    return {"metrics": metrics, "alerts": alerts}


async def attendance(conn, org_id) -> dict:
    totals = await conn.fetchrow(
        "select count(*) filter (where success) as logins, "
        "count(*) filter (where not success) as failed, "
        "count(distinct user_id) filter (where success) as active_users "
        "from login_events where organization_id=$1 and created_at >= now() - interval '30 days'", org_id)
    per_day = await conn.fetch(
        "select date_trunc('day', created_at)::date as day, "
        "count(*) filter (where success) as logins, count(*) filter (where not success) as failed "
        "from login_events where organization_id=$1 and created_at >= now() - interval '14 days' "
        "group by 1 order by 1", org_id)
    top = await conn.fetch(
        "select u.login, count(*) as logins from login_events e join users u on u.id=e.user_id "
        "where e.organization_id=$1 and e.success and e.created_at >= now() - interval '30 days' "
        "group by u.login order by count(*) desc limit 5", org_id)
    return {
        "totals": {"logins": totals["logins"], "failed": totals["failed"], "active_users": totals["active_users"]},
        "per_day": [{"day": r["day"].isoformat(), "logins": r["logins"], "failed": r["failed"]} for r in per_day],
        "top_users": [{"login": r["login"], "logins": r["logins"]} for r in top],
    }


async def popularity(conn, org_id, days: int = 30) -> dict:
    """Популярность дашбордов по просмотрам (audit_log action=view) за период.

    Учитывает только существующие дашборды (join). Просмотры троттлятся на
    уровне логирования, поэтому счётчик ≈ число сессий просмотра.
    """
    totals = await conn.fetchrow(
        "select count(*) as views, count(distinct actor_user_id) as viewers "
        "from audit_log where organization_id=$1 and action='view' "
        "and created_at >= now() - ($2 || ' days')::interval", org_id, str(days))
    top = await conn.fetch(
        "select d.id, d.name, count(*) as views, count(distinct a.actor_user_id) as viewers, "
        "max(a.created_at) as last_view "
        "from audit_log a join dashboards d on d.id=a.entity_id "
        "where a.organization_id=$1 and a.action='view' "
        "and a.created_at >= now() - ($2 || ' days')::interval "
        "group by d.id, d.name order by count(*) desc, max(a.created_at) desc limit 10", org_id, str(days))
    return {
        "days": days,
        "totals": {"views": totals["views"], "viewers": totals["viewers"]},
        "top_dashboards": [{
            "dashboard_id": str(r["id"]), "name": r["name"], "views": r["views"], "viewers": r["viewers"],
            "last_view": r["last_view"].isoformat() if r["last_view"] else None,
        } for r in top],
    }


async def dashboard_viewers(conn, org_id, dashboard_id: str, days: int = 30) -> dict:
    """Отчёт по конкретному дашборду: кто его смотрел (req #4/#5, фильтр по дашборду)."""
    d = await conn.fetchrow(
        "select name from dashboards where id=$1::uuid and organization_id=$2", dashboard_id, org_id)
    rows = await conn.fetch(
        "select coalesce(u.full_name, u.login) as who, u.login, count(*) as views, "
        "max(a.created_at) as last_view "
        "from audit_log a join users u on u.id=a.actor_user_id "
        "where a.organization_id=$1 and a.action='view' and a.entity_id=$2::uuid "
        "and a.created_at >= now() - make_interval(days => $3) "
        "group by u.full_name, u.login order by count(*) desc", org_id, dashboard_id, days)
    return {
        "dashboard_id": dashboard_id,
        "name": d["name"] if d else "(дашборд удалён)",
        "days": days,
        "viewers": [{
            "who": r["who"], "login": r["login"], "views": r["views"],
            "last_view": r["last_view"].isoformat() if r["last_view"] else None,
        } for r in rows],
    }


async def moderation_stats(conn, org_id, days: int = 30) -> dict:
    """Отчёт по модерации: очередь сейчас + статистика заявок/решений за период.

    Заявки не имеют organization_id напрямую — берём через dashboard.
    Причина возврата хранится в publication_reviews.comment как «[CODE] …».
    """
    pending = await conn.fetchval(
        "select count(*) from publication_requests pr join dashboards d on d.id=pr.dashboard_id "
        "where d.organization_id=$1 and pr.status='pending_moderation'", org_id)
    tot = await conn.fetchrow(
        "select "
        "count(*) filter (where pr.status='approved') as approved, "
        "count(*) filter (where pr.status='returned_for_revision') as returned, "
        "count(*) filter (where pr.status='cancelled') as cancelled, "
        "avg(extract(epoch from (pr.resolved_at - pr.requested_at))) "
        "  filter (where pr.resolved_at is not null) as avg_sec "
        "from publication_requests pr join dashboards d on d.id=pr.dashboard_id "
        "where d.organization_id=$1 and pr.requested_at >= now() - make_interval(days => $2)", org_id, days)
    reasons = await conn.fetch(
        "select coalesce(rc.label_ru, m.code, '(без причины)') as label, count(*) as n "
        "from publication_reviews rv "
        "join publication_requests pr on pr.id=rv.publication_request_id "
        "join dashboards d on d.id=pr.dashboard_id "
        "cross join lateral (select substring(rv.comment from '^\\[([A-Z_]+)\\]') as code) m "
        "left join moderation_reason_code rc on rc.code = m.code "
        "where d.organization_id=$1 and rv.decision='rejected' "
        "and rv.created_at >= now() - make_interval(days => $2) "
        "group by coalesce(rc.label_ru, m.code, '(без причины)') order by count(*) desc limit 5", org_id, days)
    reviewers = await conn.fetch(
        "select u.login, "
        "count(*) filter (where rv.decision='approved') as approved, "
        "count(*) filter (where rv.decision='rejected') as returned "
        "from publication_reviews rv "
        "join publication_requests pr on pr.id=rv.publication_request_id "
        "join dashboards d on d.id=pr.dashboard_id "
        "join users u on u.id=rv.reviewer_id "
        "where d.organization_id=$1 and rv.created_at >= now() - make_interval(days => $2) "
        "group by u.login order by count(*) desc limit 5", org_id, days)

    approved = tot["approved"] or 0
    returned = tot["returned"] or 0
    resolved = approved + returned
    avg_sec = tot["avg_sec"]
    return {
        "days": days,
        "pending": pending,
        "totals": {
            "approved": approved,
            "returned": returned,
            "cancelled": tot["cancelled"] or 0,
            "avg_hours": round(avg_sec / 3600, 1) if avg_sec else None,
            "return_rate": round(returned / resolved * 100) if resolved else None,
        },
        "top_reasons": [{"label": r["label"], "count": r["n"]} for r in reasons],
        "top_reviewers": [{"login": r["login"], "approved": r["approved"], "returned": r["returned"]} for r in reviewers],
    }
