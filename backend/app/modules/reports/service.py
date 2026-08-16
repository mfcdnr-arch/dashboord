"""Сервис отчётов.

Системный мониторинг (Q5): CPU/RAM/диск через psutil + статусы сервисов
(PostgreSQL/Redis/MinIO) + размер БД, с уровнями-порогами (good/warn/danger).
Посещаемость: агрегаты по login_events (входы/неудачи/активные, по дням, топ).
Сбор локальный, on-prem, без внешних SaaS.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import date, timedelta
from typing import Optional

import psutil
from fastapi.concurrency import run_in_threadpool

from ...config import settings
from ..dashboards import service as dash_svc
from ..documents import storage
from ..metrics import resolver as mr
from ..metrics.parser import FormulaError
from ..system import settings_service as settings_svc

# --------------------------------------------------------------------------- #
# Период отчёта (п. 4 списка заказчика: фильтрация)
# --------------------------------------------------------------------------- #
# Раньше период был зашит в запросы (30 дней у посещаемости, 14 у графика по
# дням). Для разбора инцидента этого мало: «кто заходил в тот вторник» и «что
# было в июле» ответить нечем. Теперь везде один и тот же диапазон дат, и он же
# уезжает в выгрузку — иначе файл не совпал бы с экраном.
DEFAULT_PERIOD_DAYS = 30
MAX_PERIOD_DAYS = 730          # два года: дальше журналы всё равно чистятся


def period_bounds(from_date: Optional[str] = None, to_date: Optional[str] = None) -> dict:
    """{start, end, days, label, clamped} — границы включительно, по датам.

    Слишком широкий запрос обрезается до MAX_PERIOD_DAYS, но НЕ молча: признак
    `clamped` уходит в ответ, и экран пишет, за что на самом деле показаны
    цифры. Молча подменить запрошенный период — то же самое, что показать не те
    данные: человек спросил про 2020 год, а увидел бы позапрошлый.
    """
    today = date.today()
    end = _as_date(to_date) or today
    start = _as_date(from_date) or (end - timedelta(days=DEFAULT_PERIOD_DAYS - 1))
    if start > end:
        start, end = end, start
    clamped = False
    if (end - start).days + 1 > MAX_PERIOD_DAYS:
        start = end - timedelta(days=MAX_PERIOD_DAYS - 1)
        clamped = True
    return {"start": start, "end": end, "days": (end - start).days + 1, "clamped": clamped,
            "label": f"{start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}"}


def _as_date(v: Optional[str]):
    if not v:
        return None
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        return None


def _level(pct: float, warn: float, crit: float) -> str:
    return "danger" if pct >= crit else ("warn" if pct >= warn else "good")


# Замер CPU занимает 0.3 с реального времени. Страницу «Здоровье системы»
# открывают и обновляют несколько администраторов сразу, плюс сторожевой cron —
# держим короткий общий кэш, чтобы не пересэмплировать на каждый запрос.
_CPU_TTL_SEC = 5.0
_cpu_cache: dict = {"value": None, "ts": 0.0}


async def _cpu_percent() -> float:
    now = time.monotonic()
    if _cpu_cache["value"] is not None and (now - _cpu_cache["ts"]) < _CPU_TTL_SEC:
        return _cpu_cache["value"]
    # cpu_percent(interval=...) СИНХРОННО спит указанное время — в корутине это
    # заблокировало бы event loop процесса API целиком. Уносим замер в поток.
    value = await run_in_threadpool(psutil.cpu_percent, 0.3)
    _cpu_cache["value"] = value
    _cpu_cache["ts"] = time.monotonic()
    return value


async def system_health(conn) -> dict:
    th = await settings_svc.get_system_settings(conn)
    cpu = await _cpu_percent()
    vm = psutil.virtual_memory()
    du = psutil.disk_usage("/")
    try:
        load = list(psutil.getloadavg())
    except (AttributeError, OSError):
        load = None
    uptime_sec = int(time.time() - psutil.boot_time())

    services = []
    t0 = time.perf_counter()
    try:
        pg_ok = (await conn.fetchval("select 1")) == 1
    except Exception:
        pg_ok = False
    pg_ms = round((time.perf_counter() - t0) * 1000, 1)
    db_size = None
    if pg_ok:
        try:
            db_size = await conn.fetchval("select pg_database_size(current_database())")
        except Exception:
            db_size = None
    services.append({"name": "PostgreSQL", "ok": pg_ok, "latency_ms": pg_ms})

    redis_ok = False
    t0 = time.perf_counter()
    try:
        import redis.asyncio as aioredis
        r = aioredis.Redis(host=settings.redis_host, port=settings.redis_port, socket_connect_timeout=1)
        redis_ok = bool(await r.ping())
        await r.aclose()
    except Exception:
        redis_ok = False
    services.append({"name": "Redis", "ok": redis_ok, "latency_ms": round((time.perf_counter() - t0) * 1000, 1)})

    minio_ok = False
    t0 = time.perf_counter()
    try:
        # Синхронный minio-клиент — в отдельном потоке (не блокировать event-loop).
        minio_ok = bool(await asyncio.to_thread(
            lambda: storage.get_client().bucket_exists(settings.minio_bucket)))
    except Exception:
        minio_ok = False
    services.append({"name": "MinIO", "ok": minio_ok, "latency_ms": round((time.perf_counter() - t0) * 1000, 1)})

    # Общий статус: degraded, если любой сервис недоступен или ресурс в danger.
    # Пороги настраиваются в UI «Настройки» (system_settings), а не только в .env.
    res_danger = any((
        _level(cpu, th["cpu_warn"], th["cpu_crit"]) == "danger",
        _level(vm.percent, th["ram_warn"], th["ram_crit"]) == "danger",
        _level(du.percent, th["disk_warn"], th["disk_crit"]) == "danger",
    ))
    overall = "degraded" if (not all(s["ok"] for s in services) or res_danger) else "ok"
    return {
        "status": overall,
        "cpu": {"percent": round(cpu, 1), "level": _level(cpu, th["cpu_warn"], th["cpu_crit"])},
        "memory": {"percent": round(vm.percent, 1), "used": vm.used, "total": vm.total,
                   "level": _level(vm.percent, th["ram_warn"], th["ram_crit"])},
        "disk": {"percent": round(du.percent, 1), "used": du.used, "total": du.total,
                 "level": _level(du.percent, th["disk_warn"], th["disk_crit"])},
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


async def attendance(conn, org_id, from_date=None, to_date=None) -> dict:
    """Посещаемость за выбранный период (по умолчанию последние 30 дней).

    График по дням строится по ТОМУ ЖЕ диапазону, что и итоги: раньше итоги
    считались за 30 дней, а график за 14, и числа под графиком не сходились с
    самим графиком.
    """
    p = period_bounds(from_date, to_date)
    args = (org_id, p["start"], p["end"])
    where = ("organization_id=$1 and created_at::date >= $2 and created_at::date <= $3")
    totals = await conn.fetchrow(
        "select count(*) filter (where success) as logins, "
        "count(*) filter (where not success) as failed, "
        "count(distinct user_id) filter (where success) as active_users "
        f"from login_events where {where}", *args)
    per_day = await conn.fetch(
        "select date_trunc('day', created_at)::date as day, "
        "count(*) filter (where success) as logins, count(*) filter (where not success) as failed "
        f"from login_events where {where} group by 1 order by 1", *args)
    top = await conn.fetch(
        "select u.login, count(*) as logins from login_events e join users u on u.id=e.user_id "
        "where e.organization_id=$1 and e.success and e.created_at::date >= $2 and e.created_at::date <= $3 "
        "group by u.login order by count(*) desc limit 5", *args)
    return {
        "period": {"from": p["start"].isoformat(), "to": p["end"].isoformat(),
                   "days": p["days"], "label": p["label"], "clamped": p["clamped"]},
        "totals": {"logins": totals["logins"], "failed": totals["failed"], "active_users": totals["active_users"]},
        "per_day": [{"day": r["day"].isoformat(), "logins": r["logins"], "failed": r["failed"]} for r in per_day],
        "top_users": [{"login": r["login"], "logins": r["logins"]} for r in top],
    }


async def popularity(conn, org_id, from_date=None, to_date=None) -> dict:
    """Популярность дашбордов по просмотрам (audit_log action=view) за период.

    Учитывает только существующие дашборды (join). Просмотры троттлятся на
    уровне логирования, поэтому счётчик ≈ число сессий просмотра.
    """
    p = period_bounds(from_date, to_date)
    args = (org_id, p["start"], p["end"])
    totals = await conn.fetchrow(
        "select count(*) as views, count(distinct actor_user_id) as viewers "
        "from audit_log where organization_id=$1 and action='view' "
        "and created_at::date >= $2 and created_at::date <= $3", *args)
    top = await conn.fetch(
        "select d.id, d.name, count(*) as views, count(distinct a.actor_user_id) as viewers, "
        "max(a.created_at) as last_view "
        "from audit_log a join dashboards d on d.id=a.entity_id "
        "where a.organization_id=$1 and a.action='view' "
        "and a.created_at::date >= $2 and a.created_at::date <= $3 "
        "group by d.id, d.name order by count(*) desc, max(a.created_at) desc limit 10", *args)
    return {
        "period": {"from": p["start"].isoformat(), "to": p["end"].isoformat(),
                   "days": p["days"], "label": p["label"], "clamped": p["clamped"]},
        "days": p["days"],
        "totals": {"views": totals["views"], "viewers": totals["viewers"]},
        "top_dashboards": [{
            "dashboard_id": str(r["id"]), "name": r["name"], "views": r["views"], "viewers": r["viewers"],
            "last_view": r["last_view"].isoformat() if r["last_view"] else None,
        } for r in top],
    }


async def dashboard_viewers(conn, org_id, dashboard_id: str, from_date=None, to_date=None) -> dict:
    """Отчёт по конкретному дашборду: кто его смотрел (req #4/#5, фильтр по дашборду)."""
    p = period_bounds(from_date, to_date)
    d = await conn.fetchrow(
        "select name from dashboards where id=$1::uuid and organization_id=$2", dashboard_id, org_id)
    rows = await conn.fetch(
        "select coalesce(u.full_name, u.login) as who, u.login, count(*) as views, "
        "max(a.created_at) as last_view "
        "from audit_log a join users u on u.id=a.actor_user_id "
        "where a.organization_id=$1 and a.action='view' and a.entity_id=$2::uuid "
        "and a.created_at::date >= $3 and a.created_at::date <= $4 "
        "group by u.full_name, u.login order by count(*) desc",
        org_id, dashboard_id, p["start"], p["end"])
    return {
        "dashboard_id": dashboard_id,
        "name": d["name"] if d else "(дашборд удалён)",
        "period": {"from": p["start"].isoformat(), "to": p["end"].isoformat(),
                   "days": p["days"], "label": p["label"], "clamped": p["clamped"]},
        "days": p["days"],
        "viewers": [{
            "who": r["who"], "login": r["login"], "views": r["views"],
            "last_view": r["last_view"].isoformat() if r["last_view"] else None,
        } for r in rows],
    }


async def moderation_stats(conn, org_id, from_date=None, to_date=None) -> dict:
    """Отчёт по модерации: очередь сейчас + статистика заявок/решений за период.

    Заявки не имеют organization_id напрямую — берём через dashboard.
    Причина возврата хранится в publication_reviews.comment как «[CODE] …».
    """
    p = period_bounds(from_date, to_date)
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
        "where d.organization_id=$1 and pr.requested_at::date >= $2 and pr.requested_at::date <= $3",
        org_id, p["start"], p["end"])
    reasons = await conn.fetch(
        "select coalesce(rc.label_ru, m.code, '(без причины)') as label, count(*) as n "
        "from publication_reviews rv "
        "join publication_requests pr on pr.id=rv.publication_request_id "
        "join dashboards d on d.id=pr.dashboard_id "
        "cross join lateral (select substring(rv.comment from '^\\[([A-Z_]+)\\]') as code) m "
        "left join moderation_reason_code rc on rc.code = m.code "
        "where d.organization_id=$1 and rv.decision='rejected' "
        "and rv.created_at::date >= $2 and rv.created_at::date <= $3 "
        "group by coalesce(rc.label_ru, m.code, '(без причины)') order by count(*) desc limit 5",
        org_id, p["start"], p["end"])
    reviewers = await conn.fetch(
        "select u.login, "
        "count(*) filter (where rv.decision='approved') as approved, "
        "count(*) filter (where rv.decision='rejected') as returned "
        "from publication_reviews rv "
        "join publication_requests pr on pr.id=rv.publication_request_id "
        "join dashboards d on d.id=pr.dashboard_id "
        "join users u on u.id=rv.reviewer_id "
        "where d.organization_id=$1 and rv.created_at::date >= $2 and rv.created_at::date <= $3 "
        "group by u.login order by count(*) desc limit 5", org_id, p["start"], p["end"])

    approved = tot["approved"] or 0
    returned = tot["returned"] or 0
    resolved = approved + returned
    avg_sec = tot["avg_sec"]
    return {
        "period": {"from": p["start"].isoformat(), "to": p["end"].isoformat(),
                   "days": p["days"], "label": p["label"], "clamped": p["clamped"]},
        "days": p["days"],
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


# --------------------------------------------------------------------------- #
# Выгрузка отчётов (п. 4 списка заказчика)
# --------------------------------------------------------------------------- #
# Экран отвечает на вопрос «как дела сейчас», а в отчёт наверх нужен файл.
# Считается ТЕМ ЖЕ кодом, что и экран (report → строки), поэтому выгрузка не
# может разойтись с тем, что человек только что видел, — та же причина, по
# которой предпросмотр разметки считается кодом выпуска.
EXPORT_KINDS = ("attendance", "popularity", "moderation", "data-quality")


async def export_report(conn, org_id, user: dict, kind: str,
                        from_date=None, to_date=None) -> tuple:
    """(заголовок листа, колонки, строки) для CSV/XLSX."""
    if kind == "attendance":
        rep = await attendance(conn, org_id, from_date, to_date)
        rows = [[r["day"], r["logins"], r["failed"]] for r in rep["per_day"]]
        rows.append(["Итого", rep["totals"]["logins"], rep["totals"]["failed"]])
        return ("Посещаемость", ["Дата", "Входов", "Неудачных попыток"], rows)
    if kind == "popularity":
        rep = await popularity(conn, org_id, from_date, to_date)
        rows = [[d["name"], d["views"], d["viewers"], _ru_dt(d["last_view"])]
                for d in rep["top_dashboards"]]
        return ("Популярность", ["Дашборд", "Просмотров", "Зрителей", "Последний просмотр"], rows)
    if kind == "moderation":
        rep = await moderation_stats(conn, org_id, from_date, to_date)
        t = rep["totals"]
        rows = [
            ["Ждут проверки сейчас", rep["pending"]],
            ["Одобрено", t["approved"]],
            ["Возвращено", t["returned"]],
            ["Отозвано", t["cancelled"]],
            ["Средний срок проверки, ч", t["avg_hours"] if t["avg_hours"] is not None else "—"],
            ["Доля возвратов, %", t["return_rate"] if t["return_rate"] is not None else "—"],
        ]
        rows += [[f"Причина возврата: {r['label']}", r["count"]] for r in rep["top_reasons"]]
        rows += [[f"Модератор {r['login']}: одобрено/возвращено",
                  f"{r['approved']}/{r['returned']}"] for r in rep["top_reviewers"]]
        return ("Модерация", ["Показатель", "Значение"], rows)
    if kind == "data-quality":
        rep = await data_quality(conn, org_id)
        rows = [[o["name"], o["datasets"], _ru_dt(o.get("last_period")),
                 _ru_dt(o.get("last_update")), o.get("status")] for o in rep.get("objects", [])]
        # Сломанные формулы в тот же файл: без них выгрузка сообщала бы, что
        # «данные в норме», умалчивая о показателях, которые не считаются.
        rows += [[f"⚠ Показатель «{m['name']}» не считается", "", "", "", m["error"]]
                 for m in rep.get("metric_errors", [])]
        return ("Качество данных",
                ["Объект", "Наборов данных", "Последний отчётный период", "Последняя загрузка", "Состояние"], rows)
    raise ValueError(f"Неизвестный отчёт: {kind}")


def _ru_dt(iso) -> str:
    """ISO-дата → ДД.ММ.ГГГГ (в файле у заказчика принят русский формат)."""
    if not iso:
        return "—"
    day = str(iso)[:10]
    parts = day.split("-")
    return ".".join(reversed(parts)) if len(parts) == 3 else day


# --------------------------------------------------------------------------- #
# Очистка истории (п. 4; только суперадминистратор)
# --------------------------------------------------------------------------- #
# Журналы копятся вечно: на дев-стенде уведомлений набралось 4460, из них 4430
# указывали в никуда. Такую ленту перестают читать, и в ней теряется важное.
#
# **Что чистится и что НЕ чистится — главное решение здесь.** Удаляем только
# следы посещения: просмотры дашбордов, записи о входах, прочитанные
# уведомления. ЗНАЧИМЫЕ действия (создание, изменение, удаление, публикация,
# выдача и отзыв доступа, выгрузки) не удаляются никогда и ни для кого: аудит
# существует, чтобы отвечать на вопрос «кто это сделал», и журнал, из которого
# можно стереть неудобную строку, не отвечает на него вовсе. Для объёма
# первичных данных есть отдельная ретенция выпусков.
HISTORY_KINDS = {
    "views": "Просмотры дашбордов",
    "logins": "Записи о входах",
    "notifications": "Прочитанные уведомления",
}
# Ниже этого порога чистить не даём: свежая история — это то, по чему разбирают
# вчерашний инцидент.
MIN_KEEP_DAYS = 30


async def history_stats(conn, org_id, older_than_days: int = 180) -> dict:
    keep = max(MIN_KEEP_DAYS, int(older_than_days or 0))
    views_total, views_old = await _pair(
        conn, "select count(*) from audit_log where organization_id=$1 and action='view'",
        "select count(*) from audit_log where organization_id=$1 and action='view' "
        "and created_at < now() - make_interval(days => $2)", org_id, keep)
    # Записи о входах: считаем И «ничьи» — попытку входа под НЕСУЩЕСТВУЮЩИМ
    # логином не к кому привязать (organization_id остаётся пустым), а именно
    # они копятся при переборе логинов. Без этого условия такие строки не
    # удалялись бы никогда: на стенде их осталось 26 из 201 при первой же
    # проверке очистки.
    logins_total, logins_old = await _pair(
        conn, "select count(*) from login_events where organization_id=$1 or organization_id is null",
        "select count(*) from login_events where (organization_id=$1 or organization_id is null) "
        "and created_at < now() - make_interval(days => $2)", org_id, keep)
    notif_total, notif_old = await _pair(
        conn, "select count(*) from notification_events where organization_id=$1",
        "select count(*) from notification_events e where e.organization_id=$1 "
        "and e.created_at < now() - make_interval(days => $2) "
        "and not exists (select 1 from notification_recipients r "
        "                where r.notification_event_id=e.id and not r.is_read)", org_id, keep)
    protected = await conn.fetchval(
        "select count(*) from audit_log where organization_id=$1 and action <> 'view'", org_id)
    return {
        "older_than_days": keep,
        "kinds": [
            {"kind": "views", "label": HISTORY_KINDS["views"], "total": views_total, "removable": views_old},
            {"kind": "logins", "label": HISTORY_KINDS["logins"], "total": logins_total, "removable": logins_old},
            {"kind": "notifications", "label": HISTORY_KINDS["notifications"],
             "total": notif_total, "removable": notif_old},
        ],
        # Показываем и то, что НЕ будет удалено: иначе «очистка истории»
        # читается как «журнал можно обнулить», а это не так.
        "protected_audit_events": protected,
    }


async def _pair(conn, sql_total, sql_old, org_id, keep) -> tuple:
    return (await conn.fetchval(sql_total, org_id) or 0,
            await conn.fetchval(sql_old, org_id, keep) or 0)


async def purge_history(conn, org_id, actor_id, kinds: list, older_than_days: int = 180) -> dict:
    """Удаляет выбранные виды истории старше порога. Возвращает, чего сколько."""
    from ..audit import service as audit_svc

    keep = max(MIN_KEEP_DAYS, int(older_than_days or 0))
    unknown = [k for k in kinds if k not in HISTORY_KINDS]
    if unknown:
        raise ValueError(f"Неизвестный вид истории: {', '.join(unknown)}")
    removed = {}
    if "views" in kinds:
        removed["views"] = await _delete_count(
            conn, "delete from audit_log where organization_id=$1 and action='view' "
            "and created_at < now() - make_interval(days => $2)", org_id, keep)
    if "logins" in kinds:
        removed["logins"] = await _delete_count(
            conn, "delete from login_events where (organization_id=$1 or organization_id is null) "
            "and created_at < now() - make_interval(days => $2)", org_id, keep)
    if "notifications" in kinds:
        # Непрочитанное не трогаем никогда: это единственное, на что человек
        # ещё может отреагировать, каким бы старым оно ни было.
        removed["notifications"] = await _delete_count(
            conn, "delete from notification_events e where e.organization_id=$1 "
            "and e.created_at < now() - make_interval(days => $2) "
            "and not exists (select 1 from notification_recipients r "
            "                where r.notification_event_id=e.id and not r.is_read)", org_id, keep)
    # Сама очистка — значимое действие, и она попадает в тот самый журнал,
    # который чистили: иначе следов не осталось бы вовсе.
    # Сущность события — сама организация: у очистки журналов своего объекта
    # нет, а колонка entity_id обязательна.
    await audit_svc.write_event(
        conn, org_id, actor_id, "delete", "history", str(org_id),
        old_data={"kinds": kinds, "older_than_days": keep, "removed": removed})
    return {"older_than_days": keep, "removed": removed, "total": sum(removed.values())}


async def _delete_count(conn, sql, *args) -> int:
    tag = await conn.execute(sql, *args)
    try:
        return int(str(tag).rsplit(" ", 1)[-1])
    except ValueError:
        return 0
