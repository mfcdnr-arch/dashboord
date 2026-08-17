"""Аналитика по ПАПКЕ объекта (п. 8 списка заказчика).

Папка — это одна форма, приходящая раз за разом: пятнадцать недель одного и
того же отчёта. Пока по ней можно было смотреть только список файлов и
собранные вручную дашборды, а вопросы у руководителя другие и всегда одни и те
же. Заказчик перечислил четыре, и здесь ровно они:

  ① **Что в цифрах** — свод показателей папки: текущее значение каждого и
     изменение к прошлому отчёту. Одним экраном, без открывания дашбордов.
  ② **Можно ли этим цифрам верить** — состояние данных: свежесть, ритм
     поступления, пропущенные отчёты, файлы, застрявшие в конвейере.
  ③ **Что уже построено, а что нет** — какие показатели показаны хоть одним
     виджетом, а какие лежат мёртвым грузом.
  ④ **Как мы на фоне других** — сравнение с остальными объектами организации
     по одноимённым показателям.

Два решения, важных для правильности:

**Ничего не считаем заново.** Значения берём тем же путём, что и виджеты
(активный выпуск по коду датасета), ритм — той же `infer_cadence`, что шлёт
уведомления о пропущенном отчёте. Иначе экран однажды разошёлся бы с
дашбордом, и верить нельзя было бы обоим.

**Объекты сравниваем по ИМЕНАМ показателей, а не по кодам.** Коды выводятся из
заголовков конкретной формы и у другого подразделения свои; имя — единственное,
что устойчиво повторяется (тот же принцип, что при тиражировании дашборда).
"""
from __future__ import annotations

from datetime import date
from typing import List

from ..maintenance.service import infer_cadence
from ..metrics import resolver as mr

# Показателей в своде может быть много (у госформы их полтора десятка), но
# сравнение объектов по КАЖДОМУ превратит экран в стену чисел.
MAX_COMPARE_FIELDS = 8


class AnalyticsError(Exception):
    pass


async def folder_analytics(conn, org_id, folder_id: str) -> dict:
    folder = await conn.fetchrow(
        "select f.id, f.name, f.object_id, o.name as object_name "
        "from folders f left join objects o on o.id=f.object_id "
        "where f.id=$1::uuid and f.organization_id=$2", folder_id, org_id)
    if folder is None:
        raise AnalyticsError("Папка не найдена")

    docs = await _documents(conn, folder_id)
    releases = await _releases(conn, org_id, folder_id)
    indicators = await _indicators(conn, org_id, releases["codes"])
    coverage = await _coverage(conn, org_id, folder_id, releases["codes"], indicators)
    return {
        "folder": {"id": str(folder["id"]), "name": folder["name"],
                   "object_id": str(folder["object_id"]) if folder["object_id"] else None,
                   "object_name": folder["object_name"]},
        "documents": docs,
        "data": releases,
        "indicators": indicators,
        "coverage": coverage,
        "objects_compare": await _compare_objects(conn, org_id, folder["object_id"], indicators),
    }


async def _documents(conn, folder_id: str) -> dict:
    """Состояние файлов в папке: сколько дошло до данных, а сколько застряло."""
    rows = await conn.fetch(
        "select d.id, d.original_filename, d.reporting_period_start, "
        "  (select j.status::text from extraction_jobs j "
        "   join document_versions v2 on v2.id=j.document_version_id "
        "   where v2.document_id=d.id order by j.created_at desc limit 1) as job_status, "
        "  exists(select 1 from dataset_releases r join document_versions v3 on v3.id=r.source_document_version_id "
        "         where v3.document_id=d.id and r.status <> 'superseded') as released "
        "from documents d where d.folder_id=$1::uuid order by d.reporting_period_start desc", folder_id)
    released = sum(1 for r in rows if r["released"])
    failed = [r for r in rows if r["job_status"] == "failed"]
    pending = [r for r in rows if not r["released"] and r["job_status"] != "failed"]
    return {
        "total": len(rows),
        "released": released,
        "not_released": len(rows) - released,
        "failed": len(failed),
        # Поимённо — то, что требует внимания: общее число «не выпущено: 3»
        # не говорит, какой именно файл открывать.
        "waiting": [{"id": str(r["id"]), "filename": r["original_filename"],
                     "period": r["reporting_period_start"].isoformat() if r["reporting_period_start"] else None,
                     "status": r["job_status"]} for r in (failed + pending)[:10]],
    }


async def _releases(conn, org_id, folder_id: str) -> dict:
    """Выпуски данных, пришедшие из этой папки: ритм, свежесть, пропуски."""
    rows = await conn.fetch(
        "select distinct r.code, r.reporting_period_start as period, r.created_at "
        "from dataset_releases r join document_versions v on v.id=r.source_document_version_id "
        "join documents d on d.id=v.document_id "
        "where d.folder_id=$1::uuid and r.organization_id=$2 and r.status <> 'superseded' "
        "order by r.reporting_period_start", folder_id, org_id)
    periods = sorted({r["period"] for r in rows if r["period"]})
    codes = sorted({r["code"] for r in rows})
    cadence = infer_cadence(periods)
    issues: List[dict] = []
    missing: List[str] = []
    today = date.today()
    overdue = None
    if cadence and periods:
        # Пропуски внутри ряда: форма приходила каждые N дней, но какой-то
        # отчёт не появился. Без этого списка дыру в данных замечают только
        # тогда, когда на графике появляется провал.
        for a, b in zip(periods, periods[1:], strict=False):
            gap = (b - a).days
            if gap > cadence * 1.5:
                step = a
                while True:
                    step = date.fromordinal(step.toordinal() + cadence)
                    if (b - step).days < cadence * 0.5:
                        break
                    missing.append(step.isoformat())
        last = periods[-1]
        expected = date.fromordinal(last.toordinal() + cadence)
        overdue = (today - expected).days
        if overdue > cadence * 0.5:
            issues.append({
                "kind": "overdue",
                "message": (f"Отчёт за {expected.strftime('%d.%m.%Y')} не поступил: "
                            f"форма приходит раз в {cadence} дн., просрочка {overdue} дн."),
            })
    if missing:
        issues.append({"kind": "gaps",
                       "message": f"В ряду не хватает отчётов: {len(missing)} (по ритму {cadence} дн.)"})
    if not periods:
        issues.append({"kind": "no_data", "message": "Из файлов этой папки ещё не выпускали данные."})
    return {
        "codes": codes,
        "releases": len(rows),
        "periods": len(periods),
        "first_period": periods[0].isoformat() if periods else None,
        "last_period": periods[-1].isoformat() if periods else None,
        "cadence_days": cadence,
        "overdue_days": overdue,
        "missing_periods": missing[:20],
        "issues": issues,
    }


async def _indicators(conn, org_id, codes: List[str]) -> List[dict]:
    """Свод показателей: текущее значение и изменение к прошлому отчёту.

    Значение берётся из АКТИВНОГО выпуска — того же, что показывают виджеты
    (`resolver._active_release`), поэтому свод не может разойтись с дашбордом.
    """
    out: List[dict] = []
    for code in codes:
        rel = await mr._active_release(conn, org_id, code)
        if rel is None:
            continue
        prev = await conn.fetchval(
            "select id from dataset_releases where organization_id=$1 and code=$2 "
            "and status <> 'superseded' and id <> $3::uuid "
            "order by reporting_period_start desc limit 1", org_id, code, rel)
        rows = await conn.fetch(
            "select drf.canonical_field_code as code, coalesce(cf.name, drf.canonical_field_code) as name, "
            "cf.unit, "
            "(select sum(v.value_number) from dataset_values v "
            " where v.dataset_release_id=$1 and v.canonical_field_code=drf.canonical_field_code) as value, "
            "(select sum(v.value_number) from dataset_values v "
            " where v.dataset_release_id=$2::uuid and v.canonical_field_code=drf.canonical_field_code) as prev_value "
            "from dataset_release_fields drf "
            "left join canonical_fields cf on cf.code=drf.canonical_field_code "
            "  and cf.object_id=(select object_id from dataset_releases where id=$1) "
            "where drf.dataset_release_id=$1 and coalesce(cf.data_type,'text')='number' "
            "order by coalesce(cf.name, drf.canonical_field_code)", rel, prev)
        for r in rows:
            value = float(r["value"]) if r["value"] is not None else None
            prev_value = float(r["prev_value"]) if r["prev_value"] is not None else None
            delta = (value - prev_value) if (value is not None and prev_value is not None) else None
            out.append({
                "dataset_code": code,
                "field": r["code"], "name": r["name"], "unit": r["unit"],
                "value": value, "prev_value": prev_value, "delta": delta,
                "delta_pct": (delta / prev_value * 100) if (delta is not None and prev_value) else None,
            })
    return out


async def _coverage(conn, org_id, folder_id: str, codes: List[str], indicators: List[dict]) -> dict:
    """Что из данных папки уже показано на дашбордах, а что нет.

    Показанным считаем поле, на которое ссылается хоть один виджет — в любом
    из мест, где поле может стоять (`value_field`, список `value_fields`,
    план и факт). Иначе показатель, выведенный полосой «план-факт», числился
    бы забытым.
    """
    dashboards = await conn.fetch(
        "select d.id, d.name, d.publication_status, "
        "(select count(*) from widgets w where w.dashboard_id=d.id) as widgets "
        "from dashboards d where d.organization_id=$1 and d.folder_id=$2::uuid "
        "and d.publication_status <> 'archived' order by d.name", org_id, folder_id)
    used: set = set()
    if codes:
        rows = await conn.fetch(
            "select w.config from widgets w join dashboards d on d.id=w.dashboard_id "
            "where w.organization_id=$1 and d.publication_status <> 'archived' "
            "and w.config->>'dataset_code' = any($2::text[])", org_id, codes)
        for r in rows:
            cfg = r["config"]
            if isinstance(cfg, str):
                import json
                cfg = json.loads(cfg)
            for key in ("value_field", "plan_field", "fact_field", "label_field"):
                if cfg.get(key):
                    used.add(cfg[key])
            for f in (cfg.get("value_fields") or []):
                used.add(f)
    missing = [{"field": i["field"], "name": i["name"]} for i in indicators if i["field"] not in used]
    return {
        "dashboards": [{"id": str(d["id"]), "name": d["name"],
                        "publication_status": d["publication_status"], "widgets": d["widgets"]}
                       for d in dashboards],
        "total_fields": len(indicators),
        "shown_fields": len(indicators) - len(missing),
        "missing_fields": missing,
    }


async def _compare_objects(conn, org_id, object_id, indicators: List[dict]) -> dict:
    """Как этот объект выглядит на фоне остальных по одноимённым показателям.

    Сопоставляем по ИМЕНАМ: коды полей выводятся из заголовков конкретной формы
    и у другого подразделения свои, а название показателя в одинаковых формах
    повторяется. Тот же принцип, что при переносе дашборда на другой объект.
    """
    if object_id is None or not indicators:
        return {"fields": [], "objects": []}
    names = [i["name"] for i in indicators[:MAX_COMPARE_FIELDS]]
    rows = await conn.fetch(
        "select o.id as object_id, o.name as object_name, cf.name as field_name, "
        "sum(v.value_number) as value "
        "from objects o "
        "join dataset_releases r on r.object_id=o.id and r.organization_id=$1 and r.status <> 'superseded' "
        "join canonical_fields cf on cf.object_id=o.id "
        "join dataset_values v on v.dataset_release_id=r.id and v.canonical_field_code=cf.code "
        "where o.organization_id=$1 and cf.name = any($2::text[]) "
        # Только последний выпуск каждого кода: иначе сложатся все недели сразу
        # и «сравнение объектов» покажет накопленную сумму вместо текущего среза.
        "and r.reporting_period_start = (select max(r2.reporting_period_start) from dataset_releases r2 "
        "  where r2.code=r.code and r2.organization_id=$1 and r2.status <> 'superseded') "
        "group by o.id, o.name, cf.name order by o.name", org_id, names)
    by_object: dict = {}
    for r in rows:
        key = str(r["object_id"])
        entry = by_object.setdefault(key, {"object_id": key, "name": r["object_name"],
                                           "is_current": key == str(object_id), "values": {}})
        entry["values"][r["field_name"]] = float(r["value"]) if r["value"] is not None else None
    objects = sorted(by_object.values(), key=lambda o: (not o["is_current"], o["name"]))
    # Один объект — сравнивать не с кем; честно отдаём пусто, чтобы экран не
    # рисовал «сравнение» из одной строки.
    return {"fields": names if len(objects) > 1 else [],
            "objects": objects if len(objects) > 1 else []}
