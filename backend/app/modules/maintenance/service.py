"""Сервис обслуживания данных: проверка свежести + ретенция (скользящее окно).

- check_freshness: по каждому объекту смотрит дату последней загрузки; если
  данные не поступали дольше stale_days — создаёт уведомление (антидубль 7 дней).
- check_cadence: вычисляет ритм поступления формы по её же истории и сообщает
  о ПРОПУЩЕННОМ отчёте — и о том, что не пришёл последний («приходило каждую
  неделю, за 12.08 файла нет»), и о дыре ВНУТРИ ряда («неделя 26.08 пропущена,
  а ряд продолжился»). Второе — разные события: дыра внутри сама собой не
  закроется и о ней надо сказать один раз, а не каждый день.
- retention_preview / run_retention: считает/удаляет релизы датасетов старше окна
  (reporting_period_start < сегодня − N месяцев). Каскад чистит values/поля/связи.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import date, timedelta
from typing import Optional

from ... import db
from ...config import settings
from ..audit import service as audit
from ..documents import storage
from ..notifications import service as notif
from ..reports import service as reports_svc
from ..system import settings_service as settings_svc


async def heal() -> dict:
    """Автопочинка прод-стека на уровне приложения: безопасные идемпотентные
    восстановления. Инфраструктурный авто-рестарт упавших контейнеров делает сам
    Docker (restart: unless-stopped в compose) — здесь то, что чинит приложение.

    Действия: (1) создать бакет MinIO, если пропал (частая проблема после сброса
    тома); (2) проверить доступность Redis. Возвращает список действий с итогом."""
    actions = []

    # (1) MinIO: гарантировать наличие бакета (idempotent — создаёт, если нет).
    # Синхронный minio-клиент — в отдельном потоке, чтобы не блокировать event-loop.
    def _ensure_bucket() -> bool:
        client = storage.get_client()
        was = client.bucket_exists(settings.minio_bucket)
        if not was:
            storage.ensure_bucket()
        return was

    t0 = time.perf_counter()
    try:
        existed = await asyncio.to_thread(_ensure_bucket)
        actions.append({
            "name": "MinIO: бакет документов",
            "ok": True,
            "result": "уже был" if existed else "создан заново",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        })
    except Exception as e:
        actions.append({"name": "MinIO: бакет документов", "ok": False, "result": f"ошибка: {e}"})

    # (2) Redis: проверить связь (перезапуск сервиса — задача Docker, не приложения).
    t0 = time.perf_counter()
    try:
        import redis.asyncio as aioredis
        r = aioredis.Redis(host=settings.redis_host, port=settings.redis_port, socket_connect_timeout=2)
        ok = bool(await r.ping())
        await r.aclose()
        actions.append({
            "name": "Redis: связь",
            "ok": ok,
            "result": "доступен" if ok else "недоступен — проверьте контейнер",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        })
    except Exception as e:
        actions.append({"name": "Redis: связь", "ok": False, "result": f"недоступен: {e}"})

    return {"actions": actions, "healthy": all(a["ok"] for a in actions)}


async def heal_and_log(conn, triggered_by: str, user_id=None, user_org_id=None) -> dict:
    """Обёртка над heal(): фиксирует статус до/после в system_heal_log (история
    ручных и автоматических починок), при ручном запуске — плюс запись в audit_log.
    triggered_by: 'manual' (кнопка админа) | 'auto' (сторожевой arq-cron)."""
    before = await reports_svc.system_health(conn)
    result = await heal()
    after = await reports_svc.system_health(conn)
    row_id = await conn.fetchval(
        "insert into system_heal_log(triggered_by, triggered_by_user_id, status_before, "
        "status_after, healthy, actions) values($1, $2::uuid, $3, $4, $5, $6::jsonb) returning id",
        triggered_by, str(user_id) if user_id else None,
        before["status"], after["status"], result["healthy"],
        json.dumps(result["actions"], ensure_ascii=False))
    if triggered_by == "manual" and user_org_id:
        await audit.write_event(
            conn, user_org_id, user_id, "heal", "system", str(row_id),
            new_data={"status_before": before["status"], "status_after": after["status"],
                      "healthy": result["healthy"]})
    return {**result, "status_before": before["status"], "status_after": after["status"]}


async def degraded_reasons(health: dict) -> list:
    """Что именно не так — словами, а не «система в состоянии degraded».

    Без этого человек идёт разбираться вслепую: причина бывает и в упавшем
    сервисе, и в ресурсах (диск, память, CPU), которые приложение чинить не
    умеет вовсе.
    """
    out = []
    for s in health.get("services") or []:
        if not s.get("ok"):
            out.append(f"{s.get('name') or s.get('code')}: недоступен")
    for key, label in (("disk", "диск"), ("memory", "память"), ("cpu", "процессор")):
        res = health.get(key) or {}
        if res.get("level") == "danger":
            out.append(f"{label} — {res.get('percent')} %")
    return out


async def notify_degraded(conn, org_id, heal_result: dict) -> None:
    """Уведомить admin/moderator организации, что система в плохом состоянии.

    Шлётся по СОСТОЯНИЮ после починки, а не по её успеху: чинить приложение
    умеет только бакет MinIO и связь с Redis, а деградацию чаще вызывают
    ресурсы — и раньше при переполненном диске починка рапортовала «здоров»
    и не сообщала никому.

    Антидубль: не чаще раза в час на организацию (иначе watchdog каждые 10
    мин спамил бы).
    """
    dup = await conn.fetchval(
        "select 1 from notification_events where organization_id=$1 and event_type='system.degraded' "
        "and created_at > now() - interval '1 hour' limit 1", org_id)
    if dup:
        return
    recipients = await notif.management_user_ids(conn, org_id)
    if not recipients:
        return
    health = await reports_svc.system_health(conn)
    await notif.notify(
        conn, org_id, "system.degraded", "organization", str(org_id),
        {"actions": heal_result["actions"], "status_after": heal_result["status_after"],
         "reasons": await degraded_reasons(health),
         "healed": heal_result.get("healthy")},
        recipients)


async def notify_worker_restarts() -> int:
    """Сообщить управляющим о перезапусках фонового воркера, о которых ещё не сообщали.

    Перезапуск делает хостовой сторож `worker-guard.sh` — из контейнера его не
    выполнить (доступа к docker.sock нет и не будет). Уведомление рассылает уже
    сторожевой cron, потому что пока воркер мёртв, рассылать некому: сам он и
    есть тот, кто шлёт уведомления.

    🔴 Отбираем по `status_before='worker_down'`, а не по `triggered_by='auto'`:
    авто-починку сторож пишет при каждом degraded, то есть каждые 10 минут, и
    рассылка по «авто» заполнила бы колокольчик за час. `worker_down` в статусе
    «до» ставит только хостовой сторож.

    Возвращает число разосланных событий (0 — обычный случай).
    """
    async with db.get_pool().acquire() as conn:
        rows = await conn.fetch(
            "select id, status_after, healthy, actions, created_at from system_heal_log "
            "where status_before = 'worker_down' and notified_at is null "
            "order by created_at limit 20")
        if not rows:
            return 0
        orgs = [r["id"] for r in await conn.fetch("select id from organizations")]
        sent = 0
        for r in rows:
            actions = json.loads(r["actions"]) if isinstance(r["actions"], str) else r["actions"]
            payload = {
                "healthy": r["healthy"],
                "status_after": r["status_after"],
                "actions": actions,
                "happened_at": r["created_at"].isoformat(),
            }
            for org_id in orgs:
                recipients = await notif.management_user_ids(conn, org_id)
                if not recipients:
                    continue
                await notif.notify(
                    conn, org_id, "system.worker_restarted", "system", str(r["id"]),
                    payload, recipients)
            await conn.execute(
                "update system_heal_log set notified_at = now() where id = $1", r["id"])
            sent += 1
        return sent


async def check_freshness(conn, org_id, stale_days: int | None = None) -> dict:
    """Создаёт уведомления по объектам с устаревшими данными. Возвращает сводку."""
    days = stale_days
    if days is None:
        days = (await settings_svc.get_org_settings(conn, org_id))["stale_days"]
    rows = await conn.fetch(
        "select o.id, o.name, max(r.created_at) as last_upload, "
        "max(r.reporting_period_start) as last_period, count(r.id) as releases "
        "from objects o left join dataset_releases r on r.object_id=o.id "
        "where o.organization_id=$1 group by o.id, o.name", org_id)
    recipients = await notif.management_user_ids(conn, org_id)
    created, stale = 0, []
    for o in rows:
        if o["releases"] == 0 or o["last_upload"] is None:
            continue  # новые объекты без данных не считаем «устаревшими»
        age_days = (await conn.fetchval("select extract(day from now() - $1)", o["last_upload"]))
        if age_days is None or age_days < days:
            continue
        stale.append({"object": o["name"], "days": int(age_days)})
        if await notif.recent_event_exists(conn, org_id, "data.stale", str(o["id"]), 7):
            continue  # уже уведомляли недавно
        await notif.notify(
            conn, org_id, "data.stale", "object", str(o["id"]),
            {"object_name": o["name"], "days_since_upload": int(age_days),
             "last_period": o["last_period"].isoformat() if o["last_period"] else None,
             "threshold_days": days},
            recipients)
        created += 1
    return {"stale_objects": stale, "notifications_created": created}


def infer_cadence(periods: list) -> Optional[int]:
    """Периодичность формы в днях по её же истории (медиана интервалов).

    Ритм не задаётся руками: заказчик просто кладёт файлы, а система смотрит,
    как они приходили. Нужно минимум 4 отчёта (три интервала) — на двух-трёх
    «ритм» был бы случайностью.

    Ритм признаётся, только если он УСТОЙЧИВ: не меньше двух третей интервалов
    отклоняются от медианы не больше чем на четверть. Иначе форма приходит
    как придётся, и говорить о пропуске нельзя — получилось бы ложное
    беспокойство на каждой нерегулярной папке.
    """
    days = sorted({p for p in periods if p is not None})
    if len(days) < 4:
        return None
    gaps = [(b - a).days for a, b in zip(days, days[1:], strict=False) if (b - a).days > 0]
    if len(gaps) < 3:
        return None
    gaps_sorted = sorted(gaps)
    median = gaps_sorted[len(gaps_sorted) // 2]
    if median <= 0:
        return None
    tolerance = max(1, round(median * 0.25))
    steady = sum(1 for g in gaps if abs(g - median) <= tolerance)
    return median if steady * 3 >= len(gaps) * 2 else None


def missing_periods(periods: list, cadence: int, until=None) -> list:
    """Отчётные даты, которых не хватает: дыры ВНУТРИ ряда и просрочка после
    последнего отчёта.

    Правило одно на систему и живёт рядом с `infer_cadence`, потому что им
    пользуются двое: аналитика папки (текстом «не хватает отчётов за …») и
    календарь поступлений (красной плиткой). Разойдись они — и один экран
    называл бы пропуском то, о чём другой молчит.

    Ряд обходится ПО ФАКТИЧЕСКИМ датам, а не отсчётом от первой: недельные
    формы кладут то в пятницу, то в понедельник, и отсчёт от начала копил бы
    сдвиг, отмечая пропуски там, где отчёт просто сместился на день.

    `until` (обычно сегодня) добавляет хвост после последнего отчёта. Дата
    считается пропущенной, только когда срок вышел больше чем на полритма, —
    тот же порог, по которому `check_cadence` шлёт уведомление: форму почти
    никогда не кладут день в день.
    """
    days = sorted({p for p in periods if p is not None})
    if not days or cadence <= 0:
        return []
    out: list = []
    for a, b in zip(days, days[1:], strict=False):
        if (b - a).days > cadence * 1.5:
            step = a
            while True:
                step = date.fromordinal(step.toordinal() + cadence)
                if (b - step).days < cadence * 0.5:
                    break
                out.append(step)
    if until is not None:
        step = days[-1]
        while True:
            step = date.fromordinal(step.toordinal() + cadence)
            if (until - step).days <= cadence * 0.5:
                break
            out.append(step)
    return out


async def check_cadence(conn, org_id) -> dict:
    """Уведомления о ПРОПУЩЕННОМ отчёте: форма приходила ритмично и не пришла.

    Проверка свежести (`check_freshness`) смотрит на возраст последней загрузки
    вообще и одинаково молчит и про недельную форму, и про годовую. Здесь
    другой вопрос: система знает, что этот датасет приходил каждую неделю
    пятнадцать раз подряд, — значит, отсутствие свежего отчёта это событие, а
    не тишина.
    """
    rows = await conn.fetch(
        "select r.code, max(o.name) as object_name, max(r.object_id::text) as object_id, "
        "array_agg(distinct r.reporting_period_start) as periods "
        "from dataset_releases r left join objects o on o.id = r.object_id "
        "where r.organization_id=$1 and r.status <> 'superseded' "
        "  and r.reporting_period_start is not null and r.object_id is not null "
        "group by r.code", org_id)
    recipients = await notif.management_user_ids(conn, org_id)
    missing, created = [], 0
    today = await conn.fetchval("select current_date")

    gaps_found: list[dict] = []
    for row in rows:
        periods = sorted(p for p in row["periods"] if p is not None)
        cadence = infer_cadence(list(row["periods"]))
        if cadence is None:
            continue

        # 🔴 Дыра ВНУТРИ ряда — отдельное событие, и до 22.09.2026 его не было
        # вовсе. Проверка ниже смотрит только на хвост: пришёл ли отчёт ПОСЛЕ
        # последнего. Поэтому пропущенная неделя, за которой ряд продолжился,
        # не давала ни уведомления, ни строки нигде — «Статистика услуг ДНР»
        # полгода показывала четыре недели вместо пяти и молчала об этом.
        #
        # Правило берём общее (`missing_periods`) — то же, которым аналитика
        # папки пишет «не хватает отчётов», а календарь красит плитку. Разойдись
        # они, один экран называл бы пропуском то, о чём молчит другой.
        gaps = missing_periods(periods, cadence)
        if gaps:
            gap_item = {"dataset_code": row["code"], "object_name": row["object_name"],
                        "object_id": row["object_id"], "cadence_days": cadence,
                        "missing": [d.isoformat() for d in gaps]}
            gaps_found.append(gap_item)
            # Дыра, которую никто не закроет, — факт постоянный, и напоминать о
            # нём каждый день значит приучить не читать уведомления. Шлём, когда
            # НАБОР дыр изменился: появилась новая или закрыли старую.
            if await _gaps_changed(conn, org_id, row["object_id"], gap_item["missing"]):
                await notif.notify(conn, org_id, "data.gap", "object", row["object_id"],
                                   gap_item, recipients)
                created += 1

        last = max(p for p in row["periods"] if p is not None)
        expected = last + timedelta(days=cadence)
        # Полритма форы: отчёт за период почти никогда не кладут день в день.
        overdue = (today - expected).days
        if overdue < max(2, cadence // 2):
            continue
        item = {"dataset_code": row["code"], "object_name": row["object_name"],
                "expected_period": expected.isoformat(), "last_period": last.isoformat(),
                "cadence_days": cadence, "overdue_days": overdue,
                "periods_seen": len(row["periods"])}
        missing.append(item)
        # Антидубль на один цикл: напоминаем не чаще, чем форма и должна приходить.
        if await notif.recent_event_exists(conn, org_id, "data.missing", row["object_id"], max(3, cadence)):
            continue
        await notif.notify(conn, org_id, "data.missing", "object", row["object_id"], item, recipients)
        created += 1
    return {"missing": missing, "gaps": gaps_found, "notifications_created": created}


async def _gaps_changed(conn, org_id, object_id, missing: list) -> bool:
    """Изменился ли набор пропущенных отчётов с прошлого уведомления.

    Сравниваем со СПИСКОМ из последнего события, а не полагаемся на окно
    времени: пропуск внутри ряда живёт, пока не пришлёт файл ведомство, то есть
    иногда вечно, и любое окно превратило бы сигнал в регулярный шум. Зато
    новая дыра обязана прозвучать сразу, каким бы старым ни было прошлое
    уведомление.
    """
    prev = await conn.fetchval(
        "select payload from notification_events where organization_id=$1 "
        "and event_type='data.gap' and entity_id=$2::uuid "
        "order by created_at desc limit 1", org_id, object_id)
    if prev is None:
        return True
    was = json.loads(prev) if isinstance(prev, str) else prev
    return list(was.get("missing") or []) != list(missing)


PREVIEW_ITEMS_LIMIT = 100


async def retention_preview(conn, org_id, months: int | None = None) -> dict:
    """Что именно будет удалено при ретенции (без удаления).

    Возвращает не только счётчики, но и ПОИМЕНОВАННЫЙ список выпусков (объект,
    код/название датасета, период, число значений) — администратор должен видеть
    в интерфейсе, что уходит, ДО необратимого удаления. Список ограничен
    PREVIEW_ITEMS_LIMIT, счётчики — по всей выборке.
    """
    m = months
    if m is None:
        m = (await settings_svc.get_org_settings(conn, org_id))["retention_months"]
    if not m or m <= 0:
        return {"enabled": False, "months": m, "releases": 0, "values": 0, "items": [], "items_limit": PREVIEW_ITEMS_LIMIT}
    rel = await conn.fetchval(
        "select count(*) from dataset_releases where organization_id=$1 "
        "and reporting_period_start < (current_date - make_interval(months => $2))", org_id, m)
    val = await conn.fetchval(
        "select count(*) from dataset_values v join dataset_releases r on r.id=v.dataset_release_id "
        "where r.organization_id=$1 and r.reporting_period_start < (current_date - make_interval(months => $2))",
        org_id, m)
    rows = await conn.fetch(
        "select r.id, r.code, r.name, r.reporting_period_start, r.status, o.name as object_name, "
        "(select count(*) from dataset_values v where v.dataset_release_id=r.id) as values_count "
        "from dataset_releases r left join objects o on o.id = r.object_id "
        "where r.organization_id=$1 and r.reporting_period_start < (current_date - make_interval(months => $2)) "
        "order by r.reporting_period_start, r.code limit $3",
        org_id, m, PREVIEW_ITEMS_LIMIT)
    items = [
        {"id": str(r["id"]), "code": r["code"], "name": r["name"], "object_name": r["object_name"],
         "status": r["status"],
         "period": r["reporting_period_start"].isoformat() if r["reporting_period_start"] else None,
         "values_count": r["values_count"]}
        for r in rows
    ]
    # Дашборды, которые ссылаются на удаляемые датасеты, — предупреждение: после
    # ретенции их виджеты останутся без данных (сами дашборды не удаляются).
    codes = sorted({i["code"] for i in items})
    affected = []
    if codes:
        affected_rows = await conn.fetch(
            "select distinct d.name from widgets w "
            "join dashboard_pages p on p.id = w.page_id "
            "join dashboards d on d.id = p.dashboard_id "
            "where d.organization_id=$1 and w.config->>'dataset_code' = any($2::text[]) order by d.name limit 20",
            org_id, codes)
        affected = [r["name"] for r in affected_rows]
    return {"enabled": True, "months": m, "releases": rel, "values": val,
            "items": items, "items_limit": PREVIEW_ITEMS_LIMIT, "affected_dashboards": affected}


async def run_retention(conn, org_id, months: int | None = None, notify_admins: bool = True) -> dict:
    """Удаляет релизы датасетов старше окна (каскадом — значения/поля/связи).

    Вызывается ТОЛЬКО по кнопке человека, рядом с предпросмотром, который
    показывает поимённо, что уйдёт. По расписанию работает `warn_retention`
    (см. ниже) — она ничего не удаляет.
    """
    m = months
    if m is None:
        m = (await settings_svc.get_org_settings(conn, org_id))["retention_months"]
    if not m or m <= 0:
        return {"enabled": False, "deleted_releases": 0}
    res = await conn.execute(
        "delete from dataset_releases where organization_id=$1 "
        "and reporting_period_start < (current_date - make_interval(months => $2))", org_id, m)
    deleted = int(res.rsplit(" ", 1)[-1]) if res.startswith("DELETE") else 0
    if deleted and notify_admins:
        recipients = await notif.management_user_ids(conn, org_id)
        await notif.notify(
            conn, org_id, "data.retention", "organization", str(org_id),
            {"deleted_releases": deleted, "window_months": m}, recipients)
    return {"enabled": True, "months": m, "deleted_releases": deleted}


async def warn_retention(conn, org_id) -> dict:
    """Еженедельная ретенция: ПРЕДУПРЕЖДАЕТ, но не удаляет (20.09.2026).

    Раньше эта же задача каждое воскресенье в 03:00 удаляла выпуски старше
    окна сама — необратимо, каскадом по значениям, без подтверждения и без
    предпросмотра. Отчётность и есть то, ради чего система существует, а
    удаление молчаливое: узнать о нём можно было только из ленты уведомлений
    постфактум, когда восстанавливать уже нечего (бэкап хранится не вечно).

    Поэтому действует тот же принцип, что принят для выпуска данных:
    **автомат готовит, решение принимает человек.** Планировщик считает, что
    попадает под отсечку, и зовёт управляющих в «Настройки», где рядом с
    кнопкой удаления показан поимённый предпросмотр. Риск здесь несимметричен:
    рост базы лечится в любой день, потеря отчётности — никогда.

    Молчит в двух случаях: ретенция выключена (окно 0) и под отсечку не
    попадает ничего — иначе еженедельное «удалять нечего» превратится в шум,
    и вместе с ним пролистают настоящее предупреждение.
    """
    m = (await settings_svc.get_org_settings(conn, org_id))["retention_months"]
    if not m or m <= 0:
        return {"enabled": False, "releases": 0, "notified": False}
    rel = await conn.fetchval(
        "select count(*) from dataset_releases where organization_id=$1 "
        "and reporting_period_start < (current_date - make_interval(months => $2))", org_id, m)
    if not rel:
        return {"enabled": True, "months": m, "releases": 0, "notified": False}
    val = await conn.fetchval(
        "select count(*) from dataset_values v join dataset_releases r on r.id=v.dataset_release_id "
        "where r.organization_id=$1 and r.reporting_period_start < (current_date - make_interval(months => $2))",
        org_id, m)
    oldest = await conn.fetchval(
        "select min(reporting_period_start) from dataset_releases where organization_id=$1 "
        "and reporting_period_start < (current_date - make_interval(months => $2))", org_id, m)
    recipients = await notif.management_user_ids(conn, org_id)
    await notif.notify(
        conn, org_id, "data.retention_due", "organization", str(org_id),
        {"releases": rel, "values": val, "window_months": m,
         "oldest": oldest.isoformat() if oldest else None}, recipients)
    return {"enabled": True, "months": m, "releases": rel, "values": val, "notified": True}


NOTIFICATION_KEEP_DAYS = 90


async def prune_notifications(conn, org_id, keep_days: int = NOTIFICATION_KEEP_DAYS) -> dict:
    """Чистка ленты уведомлений: прочитанное старьё и события «в никуда».

    Уведомления копились без ограничения: на стенде их набралось больше четырёх
    тысяч, и колокольчик показывал «99+» из событий полугодовой давности —
    такую ленту перестают читать вовсе, и в ней теряется важное.

    Удаляем два вида. (1) Прочитанные всеми получателями и старше окна —
    непрочитанное не трогаем никогда, каким бы старым оно ни было: это
    единственное, на что человек ещё может отреагировать. (2) События, чья
    сущность удалена: клик по такому уведомлению приводит в пустоту («Обращение
    не найдено»), пользы от него нет.
    """
    orphan = await conn.execute(
        "delete from notification_events e where e.organization_id=$1 and ("
        "  (e.entity_type='appeal'    and not exists (select 1 from appeals a    where a.id = e.entity_id)) or"
        "  (e.entity_type='dashboard' and not exists (select 1 from dashboards d where d.id = e.entity_id)) or"
        "  (e.entity_type='object'    and not exists (select 1 from objects o    where o.id = e.entity_id)) or"
        "  (e.entity_type='widget'    and not exists (select 1 from widgets w    where w.id = e.entity_id)))",
        org_id)
    old = await conn.execute(
        "delete from notification_events e where e.organization_id=$1 "
        "  and e.created_at < now() - make_interval(days => $2) "
        "  and not exists (select 1 from notification_recipients r "
        "                  where r.notification_event_id = e.id and not r.is_read)",
        org_id, keep_days)

    def _n(res: str) -> int:
        return int(res.rsplit(" ", 1)[-1]) if res.startswith("DELETE") else 0

    return {"orphaned": _n(orphan), "old_read": _n(old), "keep_days": keep_days}


async def heal_history(conn, limit: int = 20) -> list[dict]:
    """Последние heal-события (ручные и автоматические) для UI «Здоровье системы»."""
    rows = await conn.fetch(
        "select sh.id, sh.triggered_by, u.login as triggered_by_login, sh.status_before, "
        "sh.status_after, sh.healthy, sh.actions, sh.created_at from system_heal_log sh "
        "left join users u on u.id = sh.triggered_by_user_id "
        "order by sh.created_at desc limit $1", limit)
    return [
        {"id": str(r["id"]), "triggered_by": r["triggered_by"], "triggered_by_login": r["triggered_by_login"],
         "status_before": r["status_before"], "status_after": r["status_after"], "healthy": r["healthy"],
         "actions": json.loads(r["actions"]), "created_at": r["created_at"].isoformat()}
        for r in rows
    ]
