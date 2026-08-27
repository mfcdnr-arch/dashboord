"""Раздел «Статистика услуг ДНР»: свод по отделениям МФЦ.

Один файл ведомства («ДНР_статистика») даёт данные СТРОКАМИ-ОТДЕЛЕНИЯМИ
(62 офиса) и СТОЛБЦАМИ-УСЛУГАМИ (блок на каждую услугу повторяется). Обычный
конструктор дашбордов под такую форму не подходит: нужен список отделений с
раскрытием по ведомству и услуге внутри — этого не даёт ни один готовый тип
виджета. Поэтому раздел собственный, а не очередной дашборд.

Числа берутся из ТЕХ ЖЕ `dataset_values`, что и обычные виджеты — АКТИВНЫЕ
(не superseded) выпуски датасета `<ведомство>_offices`, без пересчёта заново.

Каждая отчётная дата — ОТДЕЛЬНЫЙ release того же кода (`reporting_period_start`),
а не столбец с датой в имени поля: новый еженедельный файл сам добавляет
точку в историю. «Прирост» везде считается между ПОСЛЕДНИМИ ДВУМЯ точками
конкретного ведомства — у разных ведомств разметка идёт не одновременно,
поэтому «последние две» для МВД и для, скажем, ФНС — не обязательно одна и
та же пара календарных дат.
"""
from __future__ import annotations

from typing import Optional

from .departments import (
    DEPARTMENTS,
    KPI_ALERT_BELOW_PCT,
    KPI_DATASET_CODE,
    KPI_SATISFACTION_ROW,
    KPI_WAIT_TIME_ROW,
    field,
)


class DnrStatsError(Exception):
    pass


async def _object_org(conn, org_id, object_id: str) -> bool:
    return bool(await conn.fetchval(
        "select 1 from objects where id=$1::uuid and organization_id=$2", object_id, org_id))


async def _active_releases(conn, org_id, object_id: str, dataset_code: str) -> list:
    """Все НЕ отменённые выпуски датасета этого объекта, старые→новые.

    Точки истории задаёт САМА жизнь данных (`dataset_releases`), а не список
    ожидаемых дат — так раздел не нужно трогать при каждом новом файле."""
    return await conn.fetch(
        "select id, reporting_period_start from dataset_releases "
        "where organization_id=$1 and object_id=$2::uuid and code=$3 and status <> 'superseded' "
        "and reporting_period_start is not null "
        "order by reporting_period_start asc, created_at asc",
        org_id, object_id, dataset_code,
    )


def _num(v) -> Optional[float]:
    return float(v) if v is not None else None


async def _dept_snapshot(conn, release, dept_code: str, dept: dict) -> dict:
    """Данные ОДНОГО выпуска ведомства, по офисам (одна точка истории)."""
    rows = await conn.fetch(
        "select row_label, canonical_field_code, value_text, value_number "
        "from dataset_values where dataset_release_id=$1", release["id"])
    by_office: dict[str, dict] = {}
    for r in rows:
        office = by_office.setdefault(r["row_label"], {"city": "", "raw": {}})
        if r["canonical_field_code"] == "gorod":
            office["city"] = r["value_text"] or ""
        else:
            office["raw"][r["canonical_field_code"]] = r

    n = len(dept["services"])
    out: dict[str, dict] = {}
    for office_label, data in by_office.items():
        raw = data["raw"]
        services = []
        total_p = total_v = 0.0
        has_any = False
        for i in range(1, n + 1):
            p = raw.get(field(dept_code, i, "prinyato"))
            v = raw.get(field(dept_code, i, "vydano"))
            prioritet = raw.get(field(dept_code, i, "prioritet"))
            okazyvaetsya = raw.get(field(dept_code, i, "okazyvaetsya"))
            pv = _num(p["value_number"]) if p else None
            vv = _num(v["value_number"]) if v else None
            services.append({
                "name": dept["services"][i - 1],
                "prioritet": prioritet["value_text"] if prioritet else None,
                "okazyvaetsya": okazyvaetsya["value_text"] if okazyvaetsya else None,
                "prinyato": pv,
                "vydano": vv,
            })
            if pv is not None:
                has_any = True
                total_p += pv
                total_v += vv or 0
        out[office_label] = {
            "city": data["city"],
            "services": services,
            "prinyato": total_p if has_any else None,
            "vydano": total_v if has_any else None,
            "period": str(release["reporting_period_start"]),
        }
    return out


async def _dept_series(conn, org_id, object_id: str, dept_code: str, dept: dict) -> list:
    """Вся история ведомства по офисам: список (период, {офис: снимок}), старые→новые."""
    releases = await _active_releases(conn, org_id, object_id, dept["dataset_code"])
    points = []
    for rel in releases:
        snap = await _dept_snapshot(conn, rel, dept_code, dept)
        points.append((str(rel["reporting_period_start"]), snap))
    return points


def _last_two(points: list):
    """(период_до, снимок_до, период_сейчас, снимок_сейчас) — последние ДВЕ
    точки истории ведомства. Если точка всего одна, «до» — пустые."""
    if not points:
        return None, {}, None, {}
    if len(points) == 1:
        p, snap = points[-1]
        return None, {}, p, snap
    (pp, ps), (np_, ns) = points[-2], points[-1]
    return pp, ps, np_, ns


async def _dept_rows(conn, org_id, object_id: str, dept_code: str, dept: dict) -> dict:
    """Свод одного ведомства по отделениям на последние два выпуска (для
    списка отделений и дашбордов ведомства/услуги — там сравнение «было/стало»,
    а не вся история)."""
    points = await _dept_series(conn, org_id, object_id, dept_code, dept)
    period_prev, snap_prev, period_now, snap_now = _last_two(points)
    if not snap_now:
        return {}

    out: dict[str, dict] = {}
    for office_label, now in snap_now.items():
        prev = snap_prev.get(office_label)
        services = []
        for i, svc_now in enumerate(now["services"]):
            svc_prev = prev["services"][i] if prev and i < len(prev["services"]) else None
            p_prev = svc_prev["prinyato"] if svc_prev else None
            v_prev = svc_prev["vydano"] if svc_prev else None
            p_now, v_now = svc_now["prinyato"], svc_now["vydano"]
            services.append({
                "name": svc_now["name"], "prioritet": svc_now["prioritet"], "okazyvaetsya": svc_now["okazyvaetsya"],
                "prinyato_prev": p_prev, "prinyato_now": p_now,
                "prirost_prinyato": (p_now - p_prev) if (p_now is not None and p_prev is not None) else None,
                "vydano_prev": v_prev, "vydano_now": v_now,
                "prirost_vydano": (v_now - v_prev) if (v_now is not None and v_prev is not None) else None,
            })
        prinyato_prev = prev["prinyato"] if prev else None
        vydano_prev = prev["vydano"] if prev else None
        out[office_label] = {
            "city": now["city"], "code": dept_code, "name": dept["name"],
            "prinyato_prev": prinyato_prev, "prinyato_now": now["prinyato"],
            "prirost": (now["prinyato"] - prinyato_prev) if (now["prinyato"] is not None and prinyato_prev is not None) else None,
            "vydano_prev": vydano_prev, "vydano_now": now["vydano"],
            "vydano_prirost": (now["vydano"] - vydano_prev) if (now["vydano"] is not None and vydano_prev is not None) else None,
            "services": services,
            "as_of": now["period"], "period_prev": period_prev, "period_now": now["period"],
        }
    return out


async def list_offices(conn, org_id, object_id: str, q: Optional[str] = None,
                       sort: str = "total_desc", dept_filter: Optional[str] = None) -> dict:
    if not await _object_org(conn, org_id, object_id):
        raise DnrStatsError("Объект не найден")

    depts = {c: d for c, d in DEPARTMENTS.items() if not dept_filter or c == dept_filter}
    per_dept = {c: await _dept_rows(conn, org_id, object_id, c, d) for c, d in depts.items()}

    offices: dict[str, dict] = {}
    period_prev = period_now = None
    for rows_by_office in per_dept.values():
        for office_label, row in rows_by_office.items():
            o = offices.setdefault(office_label, {
                "office": office_label, "city": row["city"],
                "prinyato_prev": 0.0, "prinyato_now": 0.0, "departments": [], "as_of": row["as_of"],
            })
            if row["prinyato_now"] is not None:
                o["prinyato_prev"] += row["prinyato_prev"] or 0
                o["prinyato_now"] += row["prinyato_now"] or 0
            o["departments"].append(row)
            period_prev, period_now = row["period_prev"], row["period_now"]

    result = []
    ql = (q or "").strip().lower()
    for o in offices.values():
        if ql and ql not in o["office"].lower() and ql not in o["city"].lower():
            continue
        o["prirost"] = o["prinyato_now"] - o["prinyato_prev"]
        o["prirost_pct"] = (o["prirost"] / o["prinyato_prev"] * 100.0) if o["prinyato_prev"] else None
        result.append(o)

    keyf = {
        "total_desc": lambda x: -x["prinyato_now"],
        "total_asc": lambda x: x["prinyato_now"],
        "growth_desc": lambda x: -(x["prirost"] or 0),
        "name": lambda x: x["office"],
    }.get(sort, lambda x: -x["prinyato_now"])
    result.sort(key=keyf)

    cities: dict[str, dict] = {}
    for o in result:
        c = cities.setdefault(o["city"] or "—", {"city": o["city"] or "—", "prinyato_now": 0.0, "prirost": 0.0})
        c["prinyato_now"] += o["prinyato_now"]
        c["prirost"] += o["prirost"]
    city_list = sorted(cities.values(), key=lambda x: -x["prinyato_now"])[:12]

    return {
        "offices": result,
        "cities": city_list,
        "departments": [{"code": c, "name": d["name"], "services": d["services"]} for c, d in DEPARTMENTS.items()],
        "total": len(result),
        "period_prev": period_prev, "period_now": period_now,
    }


async def office_department(conn, org_id, object_id: str, office: str, dept_code: str) -> dict:
    """Дашборд одного ведомства для ОДНОГО отделения: карточки, ряд по
    последним двум отчётным точкам этого ведомства и место среди отделений.

    Место считается ПО ТЕМ ЖЕ ИТОГАМ, что видно в списке «Отделения» — иначе
    экран сказал бы «3-е место», а список отделений показывал бы другую
    цифру для той же пары «отделение · ведомство».
    """
    if not await _object_org(conn, org_id, object_id):
        raise DnrStatsError("Объект не найден")
    dept = DEPARTMENTS.get(dept_code)
    if dept is None:
        raise DnrStatsError("Ведомство не найдено")

    rows_by_office = await _dept_rows(conn, org_id, object_id, dept_code, dept)
    row = rows_by_office.get(office)
    if row is None:
        raise DnrStatsError("Отделение не найдено в данных этого ведомства")

    ranked = sorted(
        ((label, r["prinyato_now"] or 0) for label, r in rows_by_office.items()),
        key=lambda x: -x[1],
    )
    place = next((i + 1 for i, (label, _) in enumerate(ranked) if label == office), None)
    top10 = [{"office": _short_office(label), "value": v} for label, v in ranked[:10]]

    active_services = sum(1 for s in row["services"] if s["okazyvaetsya"] not in (None, "нет"))
    conversion = (row["vydano_now"] / row["prinyato_now"] * 100.0) if row["prinyato_now"] else None

    return {
        "office": office, "city": row["city"], "department": {"code": dept_code, "name": dept["name"]},
        "as_of": row["as_of"], "period_prev": row["period_prev"], "period_now": row["period_now"],
        "prinyato_prev": row["prinyato_prev"], "prinyato_now": row["prinyato_now"], "prirost": row["prirost"],
        "vydano_prev": row["vydano_prev"], "vydano_now": row["vydano_now"], "vydano_prirost": row["vydano_prirost"],
        "conversion_pct": conversion, "active_services": active_services, "total_services": len(dept["services"]),
        "services": row["services"],
        "rank": {"place": place, "total": len(ranked), "top10": top10},
    }


async def office_service(conn, org_id, object_id: str, office: str, dept_code: str, idx: int) -> dict:
    """Дашборд ОДНОЙ услуги для одного отделения: та же карточка-логика, что
    и у дашборда ведомства, но числа и место — только по этой услуге.

    `idx` — порядковый номер услуги (1..N), а не её название: имена услуг —
    длинные официальные формулировки со скобками и кавычками (см. «Криптобио-
    кабина»), гонять их в query-параметре надёжности не добавляет.
    """
    if not await _object_org(conn, org_id, object_id):
        raise DnrStatsError("Объект не найден")
    dept = DEPARTMENTS.get(dept_code)
    if dept is None:
        raise DnrStatsError("Ведомство не найдено")
    if not (1 <= idx <= len(dept["services"])):
        raise DnrStatsError("Услуга не найдена")

    rows_by_office = await _dept_rows(conn, org_id, object_id, dept_code, dept)
    row = rows_by_office.get(office)
    if row is None:
        raise DnrStatsError("Отделение не найдено в данных этого ведомства")
    svc = row["services"][idx - 1]

    ranked = sorted(
        ((label, (r["services"][idx - 1]["prinyato_now"] or 0)) for label, r in rows_by_office.items()),
        key=lambda x: -x[1],
    )
    place = next((i + 1 for i, (label, _) in enumerate(ranked) if label == office), None)
    top10 = [{"office": _short_office(label), "value": v} for label, v in ranked[:10]]
    conversion = (svc["vydano_now"] / svc["prinyato_now"] * 100.0) if svc["prinyato_now"] else None

    return {
        "office": office, "city": row["city"], "department": {"code": dept_code, "name": dept["name"]},
        "as_of": row["as_of"], "period_prev": row["period_prev"], "period_now": row["period_now"],
        "service": svc, "service_index": idx,
        "conversion_pct": conversion,
        "rank": {"place": place, "total": len(ranked), "top10": top10},
    }


async def _kpi_snapshot(conn, org_id) -> Optional[dict]:
    """Последний выпуск паспорта КПЭ учреждения — org-wide по коду датасета,
    независимо от того, к какому объекту привязана «Статистика услуг»: КПЭ
    один на организацию и размечен отдельно."""
    release = await conn.fetchrow(
        "select id, reporting_period_start from dataset_releases "
        "where organization_id=$1 and code=$2 and status <> 'superseded' "
        "order by reporting_period_start desc nulls last, created_at desc limit 1",
        org_id, KPI_DATASET_CODE)
    if release is None:
        return None
    values = await conn.fetch(
        "select row_index, row_label, canonical_field_code, value_text, value_number "
        "from dataset_values where dataset_release_id=$1 order by row_index", release["id"])
    by_row: dict[int, dict] = {}
    for r in values:
        row = by_row.setdefault(r["row_index"], {"name": r["row_label"]})
        if r["canonical_field_code"] == "edinica_izmereniya":
            row["unit"] = r["value_text"]
        elif r["canonical_field_code"] in ("plan", "fakt", "dostizheniya_pokazatelya"):
            row[r["canonical_field_code"]] = _num(r["value_number"])
    rows = [{"index": i + 1, **v} for i, v in enumerate(dict(sorted(by_row.items())).values())]
    return {
        "as_of": str(release["reporting_period_start"]) if release["reporting_period_start"] else None,
        "rows": rows,
    }


def _service_label(text: str, limit: int = 90) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


async def overview(conn, org_id, object_id: str) -> dict:
    """Сводный «Обзор» — верхний уровень над списком отделений: главные
    KPI-карточки, тренд по ВСЕМ накопленным датам срезов, разбивка по
    ведомствам и лента алертов.

    Строится по ТЕМ ЖЕ данным, что список отделений и дашборды ведомства/
    услуги (`_dept_series`/`_kpi_snapshot`) — второго источника правды нет.
    Масштабируется сам: ведомств может быть 1 или 12, дат-срезов 2 или 50 —
    код одинаково проходит по тому, что реально накопилось в `dataset_releases`.
    """
    if not await _object_org(conn, org_id, object_id):
        raise DnrStatsError("Объект не найден")

    dept_points: dict[str, list] = {}
    for code, dept in DEPARTMENTS.items():
        points = await _dept_series(conn, org_id, object_id, code, dept)
        if points:
            dept_points[code] = points

    # --- Тренд по всем датам срезов: сумма по ведомствам на каждую дату, где
    # хоть у одного ведомства есть данные (ведомства размечаются не разом). ---
    by_period: dict[str, list] = {}
    for points in dept_points.values():
        for period, snap in points:
            by_period.setdefault(period, []).append(snap)
    trend = []
    for period in sorted(by_period):
        tp = tv = 0.0
        any_data = False
        for snap in by_period[period]:
            for office in snap.values():
                if office["prinyato"] is not None:
                    any_data = True
                    tp += office["prinyato"]
                    tv += office["vydano"] or 0
        if any_data:
            trend.append({"period": period, "prinyato": tp, "vydano": tv})

    # --- По ведомствам: последняя точка + прирост к СВОЕЙ предыдущей. ---
    dept_summary = []
    offices_now: set[str] = set()
    zero_growth: dict[str, float] = {}
    total_prinyato = total_vydano = 0.0
    total_growth = 0.0
    has_growth = False
    total_services = 0
    services_total_names: list[str] = []
    services_missing: list[str] = []
    for code, points in dept_points.items():
        dept = DEPARTMENTS[code]
        period_prev, snap_prev, period_now, snap_now = _last_two(points)
        dp = dv = 0.0
        for office_label, row in snap_now.items():
            if row["prinyato"] is None:
                continue
            offices_now.add(office_label)
            dp += row["prinyato"]
            dv += row["vydano"] or 0
            prev_row = snap_prev.get(office_label)
            if prev_row and prev_row["prinyato"] is not None:
                growth = row["prinyato"] - prev_row["prinyato"]
                zero_growth[office_label] = zero_growth.get(office_label, 0.0) + growth
        prev_total = None
        if snap_prev:
            prev_vals = [r["prinyato"] for r in snap_prev.values() if r["prinyato"] is not None]
            prev_total = sum(prev_vals) if prev_vals else None
        growth_dept = (dp - prev_total) if prev_total is not None else None
        dept_summary.append({
            "code": code, "name": dept["name"], "prinyato": dp, "vydano": dv,
            "growth": growth_dept, "period_prev": period_prev, "period_now": period_now,
        })
        total_prinyato += dp
        total_vydano += dv
        if growth_dept is not None:
            total_growth += growth_dept
            has_growth = True

        n = len(dept["services"])
        offered_anywhere = [False] * n
        for row in snap_now.values():
            for i, svc in enumerate(row["services"]):
                if svc["okazyvaetsya"] not in (None, "", "нет"):
                    offered_anywhere[i] = True
        total_services += n
        for i, ok in enumerate(offered_anywhere):
            services_total_names.append(dept["services"][i])
            if not ok:
                services_missing.append(dept["services"][i])

    dept_summary.sort(key=lambda x: -(x["growth"] or -1e18))
    leader = next((d for d in dept_summary if d["growth"] is not None), None)

    zero_growth_offices = sorted(
        [(label, g) for label, g in zero_growth.items() if g <= 0], key=lambda x: x[1])

    conversion = (total_vydano / total_prinyato * 100.0) if total_prinyato else None
    services_active = total_services - len(services_missing)

    kpi = await _kpi_snapshot(conn, org_id)
    kpi_rows = kpi["rows"] if kpi else []
    satisfaction = next((r for r in kpi_rows if r["name"] == KPI_SATISFACTION_ROW), None)
    wait_time = next((r for r in kpi_rows if r["name"] == KPI_WAIT_TIME_ROW), None)
    kpi_alerts = [r for r in kpi_rows if r.get("dostizheniya_pokazatelya") is not None
                  and r["dostizheniya_pokazatelya"] < KPI_ALERT_BELOW_PCT]

    alerts = []
    for label, _g in zero_growth_offices[:5]:
        alerts.append({"kind": "zero_growth", "text": f"Нулевой прирост заявлений за период: {label}"})
    if services_missing:
        example = _service_label(services_missing[0])
        alerts.append({
            "kind": "service_gap",
            "text": f"Не оказывается услуг: {len(services_missing)} из {total_services} (например, «{example}»)",
        })
    for r in kpi_alerts:
        pct = r["dostizheniya_pokazatelya"]
        alerts.append({
            "kind": "kpi", "text": f"КПЭ №{r['index']} «{_service_label(r['name'], 60)}» — {pct:.1f}% плана",
        })
    if wait_time and wait_time.get("plan") and wait_time.get("fakt") is not None:
        over = wait_time["fakt"] - wait_time["plan"]
        if over > 0:
            alerts.append({
                "kind": "wait_time",
                "text": f"Среднее время ожидания {wait_time['fakt']:.2f} мин при плане {wait_time['plan']:.0f} мин",
            })

    return {
        "as_of": trend[-1]["period"] if trend else None,
        "period_prev": trend[-2]["period"] if len(trend) >= 2 else None,
        "kpi_as_of": kpi["as_of"] if kpi else None,
        "totals": {
            "prinyato": total_prinyato, "vydano": total_vydano,
            "growth": total_growth if has_growth else None,
            "conversion_pct": conversion,
        },
        "offices_total": len(offices_now),
        "offices_no_growth": len(zero_growth_offices),
        "services_total": total_services,
        "services_active": services_active,
        "leader": leader,
        "departments": dept_summary,
        "trend": trend,
        "satisfaction": satisfaction,
        "wait_time": wait_time,
        "alerts": alerts,
    }


def _short_office(label: str) -> str:
    """Короткая подпись отделения для графика рейтинга — полный адрес туда
    не влезает; город обычно узнаваем по началу названия."""
    for marker in ("г. ", "г."):
        i = label.find(marker)
        if i != -1:
            rest = label[i + len(marker):]
            return rest.split(",")[0].strip()
    return label[:20]
