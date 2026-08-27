"""Раздел «Статистика услуг ДНР»: свод по отделениям МФЦ.

Один файл ведомства («ДНР_статистика») даёт данные СТРОКАМИ-ОТДЕЛЕНИЯМИ
(62 офиса) и СТОЛБЦАМИ-УСЛУГАМИ (блок на каждую услугу повторяется). Обычный
конструктор дашбордов под такую форму не подходит: нужен список отделений с
раскрытием по ведомству и услуге внутри — этого не даёт ни один готовый тип
виджета. Поэтому раздел собственный, а не очередной дашборд.

Числа берутся из ТЕХ ЖЕ `dataset_values`, что и обычные виджеты — активный
(не superseded) выпуск датасета `<ведомство>_offices`, без пересчёта заново.
"""
from __future__ import annotations

from typing import Optional

from .departments import DEPARTMENTS, field


class DnrStatsError(Exception):
    pass


async def _object_org(conn, org_id, object_id: str) -> bool:
    return bool(await conn.fetchval(
        "select 1 from objects where id=$1::uuid and organization_id=$2", object_id, org_id))


async def _active_release(conn, org_id, object_id: str, dataset_code: str):
    return await conn.fetchrow(
        "select id, reporting_period_start from dataset_releases "
        "where organization_id=$1 and object_id=$2::uuid and code=$3 and status <> 'superseded' "
        "order by reporting_period_start desc nulls last, created_at desc limit 1",
        org_id, object_id, dataset_code,
    )


def _num(v) -> Optional[float]:
    return float(v) if v is not None else None


async def _dept_rows(conn, org_id, object_id: str, dept_code: str, dept: dict) -> dict:
    """Данные одного ведомства, сгруппированные по отделению (row_label)."""
    release = await _active_release(conn, org_id, object_id, dept["dataset_code"])
    if release is None:
        return {}
    rows = await conn.fetch(
        "select row_label, canonical_field_code, value_text, value_number "
        "from dataset_values where dataset_release_id=$1", release["id"])
    by_office: dict[str, dict] = {}
    n = len(dept["services"])
    for r in rows:
        office = by_office.setdefault(r["row_label"], {"city": "", "raw": {}})
        if r["canonical_field_code"] == "gorod":
            office["city"] = r["value_text"] or ""
        else:
            office["raw"][r["canonical_field_code"]] = r

    out = {}
    for office_label, data in by_office.items():
        raw = data["raw"]
        services = []
        t_p12 = t_p19 = t_v12 = t_v19 = 0.0
        has_any = False
        for i in range(1, n + 1):
            p12 = raw.get(field(dept_code, i, "prinyato_12"))
            p19 = raw.get(field(dept_code, i, "prinyato_19"))
            pp = raw.get(field(dept_code, i, "prinyato_prirost"))
            v12 = raw.get(field(dept_code, i, "vydano_12"))
            v19 = raw.get(field(dept_code, i, "vydano_19"))
            vp = raw.get(field(dept_code, i, "vydano_prirost"))
            prioritet = raw.get(field(dept_code, i, "prioritet"))
            okazyvaetsya = raw.get(field(dept_code, i, "okazyvaetsya"))
            svc = {
                "name": dept["services"][i - 1],
                "prioritet": prioritet["value_text"] if prioritet else None,
                "okazyvaetsya": okazyvaetsya["value_text"] if okazyvaetsya else None,
                "prinyato_12": _num(p12["value_number"]) if p12 else None,
                "prinyato_19": _num(p19["value_number"]) if p19 else None,
                "prirost_prinyato": _num(pp["value_number"]) if pp else None,
                "vydano_12": _num(v12["value_number"]) if v12 else None,
                "vydano_19": _num(v19["value_number"]) if v19 else None,
                "prirost_vydano": _num(vp["value_number"]) if vp else None,
            }
            services.append(svc)
            if svc["prinyato_19"] is not None:
                has_any = True
                t_p12 += svc["prinyato_12"] or 0
                t_p19 += svc["prinyato_19"] or 0
                t_v12 += svc["vydano_12"] or 0
                t_v19 += svc["vydano_19"] or 0
        out[office_label] = {
            "city": data["city"],
            "code": dept_code,
            "name": dept["name"],
            "prinyato_12": t_p12 if has_any else None,
            "prinyato_19": t_p19 if has_any else None,
            "prirost": (t_p19 - t_p12) if has_any else None,
            "vydano_12": t_v12 if has_any else None,
            "vydano_19": t_v19 if has_any else None,
            "vydano_prirost": (t_v19 - t_v12) if has_any else None,
            "services": services,
            "as_of": str(release["reporting_period_start"]) if release["reporting_period_start"] else None,
        }
    return out


async def list_offices(conn, org_id, object_id: str, q: Optional[str] = None,
                       sort: str = "total_desc", dept_filter: Optional[str] = None) -> dict:
    if not await _object_org(conn, org_id, object_id):
        raise DnrStatsError("Объект не найден")

    depts = {c: d for c, d in DEPARTMENTS.items() if not dept_filter or c == dept_filter}
    per_dept = {c: await _dept_rows(conn, org_id, object_id, c, d) for c, d in depts.items()}

    offices: dict[str, dict] = {}
    for code, rows_by_office in per_dept.items():
        for office_label, row in rows_by_office.items():
            o = offices.setdefault(office_label, {
                "office": office_label, "city": row["city"],
                "prinyato_12": 0.0, "prinyato_19": 0.0, "departments": [], "as_of": row["as_of"],
            })
            if row["prinyato_19"] is not None:
                o["prinyato_12"] += row["prinyato_12"] or 0
                o["prinyato_19"] += row["prinyato_19"] or 0
            o["departments"].append(row)

    result = []
    ql = (q or "").strip().lower()
    for o in offices.values():
        if ql and ql not in o["office"].lower() and ql not in o["city"].lower():
            continue
        o["prirost"] = o["prinyato_19"] - o["prinyato_12"]
        o["prirost_pct"] = (o["prirost"] / o["prinyato_12"] * 100.0) if o["prinyato_12"] else None
        result.append(o)

    keyf = {
        "total_desc": lambda x: -x["prinyato_19"],
        "total_asc": lambda x: x["prinyato_19"],
        "growth_desc": lambda x: -(x["prirost"] or 0),
        "name": lambda x: x["office"],
    }.get(sort, lambda x: -x["prinyato_19"])
    result.sort(key=keyf)

    cities: dict[str, dict] = {}
    for o in result:
        c = cities.setdefault(o["city"] or "—", {"city": o["city"] or "—", "prinyato_19": 0.0, "prirost": 0.0})
        c["prinyato_19"] += o["prinyato_19"]
        c["prirost"] += o["prirost"]
    city_list = sorted(cities.values(), key=lambda x: -x["prinyato_19"])[:12]

    return {
        "offices": result,
        "cities": city_list,
        "departments": [{"code": c, "name": d["name"], "services": d["services"]} for c, d in DEPARTMENTS.items()],
        "total": len(result),
    }


async def office_department(conn, org_id, object_id: str, office: str, dept_code: str) -> dict:
    """Дашборд одного ведомства для ОДНОГО отделения (скрин 3): карточки,
    ряд по двум отчётным точкам («на 12.08» / «на 19.08» — третьей ДАТЫ у нас
    пока нет, история копится по мере новых выпусков) и место среди отделений.

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
        ((label, r["prinyato_19"] or 0) for label, r in rows_by_office.items()),
        key=lambda x: -x[1],
    )
    place = next((i + 1 for i, (label, _) in enumerate(ranked) if label == office), None)
    top10 = [{"office": _short_office(label), "value": v} for label, v in ranked[:10]]

    active_services = sum(1 for s in row["services"] if s["okazyvaetsya"] not in (None, "нет"))
    conversion = (row["vydano_19"] / row["prinyato_19"] * 100.0) if row["prinyato_19"] else None

    return {
        "office": office, "city": row["city"], "department": {"code": dept_code, "name": dept["name"]},
        "as_of": row["as_of"],
        "prinyato_12": row["prinyato_12"], "prinyato_19": row["prinyato_19"], "prirost": row["prirost"],
        "vydano_12": row["vydano_12"], "vydano_19": row["vydano_19"], "vydano_prirost": row["vydano_prirost"],
        "conversion_pct": conversion, "active_services": active_services, "total_services": len(dept["services"]),
        "services": row["services"],
        "rank": {"place": place, "total": len(ranked), "top10": top10},
    }


async def office_service(conn, org_id, object_id: str, office: str, dept_code: str, idx: int) -> dict:
    """Дашборд ОДНОЙ услуги для одного отделения (скрин 2): та же карточка-логика,
    что и у дашборда ведомства, но числа и место — только по этой услуге, а не
    по сумме всех услуг ведомства.

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
        ((label, (r["services"][idx - 1]["prinyato_19"] or 0)) for label, r in rows_by_office.items()),
        key=lambda x: -x[1],
    )
    place = next((i + 1 for i, (label, _) in enumerate(ranked) if label == office), None)
    top10 = [{"office": _short_office(label), "value": v} for label, v in ranked[:10]]
    conversion = (svc["vydano_19"] / svc["prinyato_19"] * 100.0) if svc["prinyato_19"] else None

    return {
        "office": office, "city": row["city"], "department": {"code": dept_code, "name": dept["name"]},
        "as_of": row["as_of"], "service": svc, "service_index": idx,
        "conversion_pct": conversion,
        "rank": {"place": place, "total": len(ranked), "top10": top10},
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
