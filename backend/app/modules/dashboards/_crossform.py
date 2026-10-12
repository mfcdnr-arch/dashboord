"""Показатели МЕЖДУ формами: «талонов на окно», «на окно-час», среднее
ожидание, взвешенное по талонам.

Числа для них лежат в разных формах: талоны — в форме «Время», окна и часы — в
форме «окна и часы». Соединить их можно только построчно (то же отделение) и
по дате (тот же день) — и только с тех пор, как названия отделений приведены к
эталону (`map/office_names`): до этого форма «Время» не совпадала с «окнами» ни
в одной строке из 61.

Конфигурация виджета — `cross`:

    {"num": [{"dataset_code", "field"}, …],   # перемножаются
     "den": [{"dataset_code", "field"}, …],   # перемножаются
     "unit": "мин" | null}

Значение — ОТНОШЕНИЕ СУММ: Σ числителя ÷ Σ знаменателя по всем совпавшим парам
«отделение × день». Не среднее частных: у отделения с одним окном и отделения
с пятнадцатью окнами «талонов на окно» весят по-разному, и среднее частных
давало бы маленькому отделению голос большого. По тому же правилу считается
взвешенное среднее: Σ(время × талоны) ÷ Σ талоны.

Строка или день, которых нет хотя бы в одной из форм, в расчёт не входят — и
виджет называет, сколько пар совпало: молча посчитанное по половине отделений
выглядело бы как цифра по всей республике.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Optional

from ._base import DashboardError
from ._rowrls import allowed_rows_for_dataset

RANKED_TOP = 5
SPARK_POINTS = 30


# Окно рейтинга и точечной диаграммы, когда период страницы не задан: сколько
# последних ДНЕЙ С ДАННЫМИ взять. «Последний день» — прежнее поведение (до
# 12.10.2026 другого не было): один день отделения — это шум (отпуск, сбой
# талонного аппарата), и разбирать по нему, где очередь, рискованно.
SPANS = {"last": 1, "7": 7, "30": 30, "all": None}
SPAN_WORDS = {"last": "последний день", "7": "последние 7 дней с данными",
              "30": "последние 30 дней с данными", "all": "вся история"}


def _parts(cfg: dict) -> tuple[list, list]:
    return _parts_of(cfg.get("cross") or {})


def _parts_of(c: dict) -> tuple[list, list]:
    num, den = c.get("num") or [], c.get("den") or []
    if not num or not den:
        raise DashboardError("Показатель между формами: укажите числитель и знаменатель")
    for p in num + den:
        if not p.get("dataset_code") or not p.get("field"):
            raise DashboardError("Показатель между формами: у каждой части нужны форма и графа")
    return num, den


def _d(v) -> Optional[date]:
    if v is None or isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


async def _load(conn, org_id, parts: list, user, from_date, to_date) -> dict:
    """{(день, строка) → {(форма, графа) → число}} по всем частям."""
    need: dict = defaultdict(set)
    for p in parts:
        need[p["dataset_code"]].add(p["field"])
    out: dict = defaultdict(dict)
    allowed_all: Optional[set] = None
    for code, fields in need.items():
        allowed = await allowed_rows_for_dataset(conn, org_id, user, code) if user is not None else None
        if allowed is not None:
            allowed_all = set(allowed) if allowed_all is None else allowed_all & set(allowed)
        rows = await conn.fetch(
            "select dr.reporting_period_start as d, dv.row_label as r, dv.canonical_field_code as f, "
            "dv.value_number as v from dataset_releases dr "
            "join dataset_values dv on dv.dataset_release_id = dr.id "
            "where dr.organization_id=$1 and dr.code=$2 and dr.status <> 'superseded' "
            "and dv.canonical_field_code = any($3::text[]) and dv.value_number is not null "
            "and coalesce(dv.row_label, '') <> '' "
            "and ($4::date is null or dr.reporting_period_start >= $4) "
            "and ($5::date is null or dr.reporting_period_start <= $5)",
            org_id, code, sorted(fields), _d(from_date), _d(to_date))
        for r in rows:
            out[(r["d"], r["r"])][(code, r["f"])] = float(r["v"])
    if allowed_all is not None:
        out = {k: v for k, v in out.items() if k[1] in allowed_all}
    return out


def _pairs(data: dict, num: list, den: list, row: Optional[str]) -> dict:
    """{(день, строка) → (числитель, знаменатель)} — только где есть ВСЁ."""
    keys_n = [(p["dataset_code"], p["field"]) for p in num]
    keys_d = [(p["dataset_code"], p["field"]) for p in den]
    out = {}
    for k, vals in data.items():
        if row and k[1] != row:
            continue
        if not all(x in vals for x in keys_n + keys_d):
            continue
        n = d = 1.0
        for x in keys_n:
            n *= vals[x]
        for x in keys_d:
            d *= vals[x]
        if d > 0:
            out[k] = (n, d)
    return out


def _ratio(pairs) -> Optional[float]:
    n = sum(p[0] for p in pairs)
    d = sum(p[1] for p in pairs)
    return n / d if d > 0 else None


async def _names(conn, org_id, parts: list) -> dict:
    out = {}
    for p in parts:
        r = await conn.fetchval(
            "select cf.name from canonical_fields cf where cf.code=$2 and cf.object_id = "
            "(select object_id from dataset_releases where organization_id=$1 and code=$3 "
            " and object_id is not null order by reporting_period_start desc nulls last limit 1)",
            org_id, p["field"], p["dataset_code"])
        out[(p["dataset_code"], p["field"])] = r or p["field"]
    return out


def _formula(names: dict, num: list, den: list) -> str:
    def side(ps):
        s = " × ".join(f"«{names[(p['dataset_code'], p['field'])]}»" for p in ps)
        return f"({s})" if len(ps) > 1 else s
    return f"{side(num)} ÷ {side(den)}"


async def compute(conn, org_id, t: str, name: str, cfg: dict,
                  from_date=None, to_date=None, row=None, user=None) -> dict:
    num, den = _parts(cfg)
    unit = (cfg.get("cross") or {}).get("unit") or cfg.get("unit")
    data = await _load(conn, org_id, num + den, user, from_date, to_date)
    pairs = _pairs(data, num, den, row)
    names = await _names(conn, org_id, num + den)
    formula = _formula(names, num, den)
    by_day: dict = defaultdict(list)
    for (d, r), p in pairs.items():
        by_day[d].append((r, p))
    days = sorted(by_day)
    base = {"title": name, "unit": unit, "cross_formula": formula}
    if not days:
        return {**base, "type": t, "value": None, "periods": [], "values": [], "rows": [],
                "no_data": "Формы не совпали ни по одному отделению и дню — сравнить нечего.",
                "cross_note": f"{formula}: общих дней с данными нет."}
    last = days[-1]

    if t == "kpi" or t == "gauge":
        today = [p for _r, p in by_day[last]]
        value = _ratio(today)
        res = {**base, "type": t, "value": value, "as_of": last.isoformat(),
               "cross_note": (f"{formula} · {len(today)} {_pl(len(today))} за {last:%d.%m.%Y}, "
                              f"совпавших в формах")}
        series = [(d, _ratio([p for _r, p in by_day[d]])) for d in days]
        if len(series) > 1:
            res["spark"] = [v for _d, v in series[-SPARK_POINTS:]]
            res["spark_periods"] = [d.isoformat() for d, _v in series[-SPARK_POINTS:]]
            pv = series[-2][1]
            if pv is not None and value is not None:
                res["prev_value"], res["prev_period"] = pv, series[-2][0].isoformat()
                res["delta"] = value - pv
                res["delta_pct"] = round((value - pv) / pv * 100, 2) if pv else None
        if t == "gauge":
            res["max"] = cfg.get("max") or (value * 1.5 if value else 1)
        return res

    if t == "dynamics":
        series = [(d, _ratio([p for _r, p in by_day[d]])) for d in days]
        vals = [v for _d, v in series]
        res = {**base, "type": "dynamics", "periods": [d.isoformat() for d, _v in series], "values": vals,
               "cross_note": f"{formula} · по дням, где совпали обе формы ({len(days)})"}
        if len(vals) > 1 and vals[0] and vals[-1] is not None:
            res.update({"total_change": vals[-1] - vals[0],
                        "total_change_pct": round((vals[-1] - vals[0]) / vals[0] * 100, 2),
                        "first_period": series[0][0].isoformat(), "last_period": series[-1][0].isoformat()})
            if vals[-2] is not None:
                res.update({"change": vals[-1] - vals[-2],
                            "change_pct": round((vals[-1] - vals[-2]) / vals[-2] * 100, 2) if vals[-2] else None,
                            "change_from_period": series[-2][0].isoformat(),
                            "change_to_period": series[-1][0].isoformat()})
        return res

    if t == "ranked":
        # С периодом страницы — все дни периода; без него — окно виджета
        # (`cross.span`: последний день, 7 или 30 дней с данными, вся история).
        use = _span_days(days, cfg.get("cross") or {}, from_date, to_date)
        per_row: dict = defaultdict(list)
        for d in use:
            for r, p in by_day[d]:
                per_row[r].append(p)
        items = sorted(({"label": r, "value": _ratio(ps)} for r, ps in per_row.items()),
                       key=lambda x: -(x["value"] or 0))
        for i, it in enumerate(items):
            it.update({"rank": i + 1, "plan": None, "pct": None, "share": None, "color": None})
        top = max(1, min(25, int(cfg.get("top_n") or RANKED_TOP)))
        if len(items) <= top * 2:
            shown, skipped = items, 0
        else:
            shown, skipped = items[:top] + items[-top:], len(items) - top * 2
        scale = [it["value"] or 0 for it in items] or [0]
        span = _span_text(use)
        on_days = set(use)
        missing = len({r for (d, r) in data if d in on_days} - set(per_row))
        return {**base, "type": "ranked", "rows": shown, "skipped": skipped, "rows_total": len(items),
                "total": None, "folded_fields": 0, "scale_max": max(scale), "rank_by": "value",
                "tied_last": 0, "tied_value": None, "as_of": last.isoformat(),
                "values_all": [it["value"] for it in items],
                "cross_note": (f"{formula} · {span}"
                               + (f" · {missing} {_pl(missing)} есть не во всех формах — не учтены"
                                  if missing > 0 else ""))}

    raise DashboardError("Показатель между формами поддерживает карточку, спидометр, динамику и рейтинг")


def _span_days(days: list, c: dict, from_date, to_date) -> list:
    if from_date or to_date:
        return days
    n = SPANS.get(str(c.get("span") or "last"), 1)
    return days if n is None else days[-n:]


def _span_text(use: list) -> str:
    return (f"за {use[0]:%d.%m.%Y}" if len(use) == 1
            else f"с {use[0]:%d.%m.%Y} по {use[-1]:%d.%m.%Y} ({len(use)} дн. с данными)")


# --- Точечная диаграмма: два показателя по отделениям ----------------------
#
# «Нагрузка на окно-час ↔ ожидание»: по горизонтали — сколько посетителей
# приходится на окно в час, по вертикали — сколько они ждут. Отделение справа
# вверху ждёт из-за нагрузки (окон мало), слева вверху — при малой нагрузке
# (медленно обслуживают или окна простаивают). Делим по МЕДИАНАМ, а не по
# среднему: одно отделение с шестичасовым «ожиданием» (сбой учёта) иначе
# сдвинуло бы черту и перетасовало всех остальных.

QUADRANTS = {
    ("hi", "hi"): "много посетителей на окно и долгое ожидание — не хватает окон",
    ("lo", "hi"): "ожидание долгое при небольшой нагрузке — смотреть скорость обслуживания",
    ("hi", "lo"): "нагрузка высокая, а ждут мало — справляются",
    ("lo", "lo"): "нагрузка и ожидание ниже обычного",
}


def _median(xs: list) -> Optional[float]:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


async def compute_scatter(conn, org_id, name: str, cfg: dict,
                          from_date=None, to_date=None, row=None, user=None) -> dict:
    sc = cfg.get("scatter") or {}
    ax, ay = sc.get("x") or {}, sc.get("y") or {}
    nx, dx = _parts_of(ax)
    ny, dy = _parts_of(ay)
    data = await _load(conn, org_id, nx + dx + ny + dy, user, from_date, to_date)
    px, py = _pairs(data, nx, dx, row), _pairs(data, ny, dy, row)
    names = await _names(conn, org_id, nx + dx + ny + dy)
    days = sorted({d for (d, _r) in px} & {d for (d, _r) in py})
    base = {"title": name, "type": "scatter",
            "x_name": ax.get("name") or _formula(names, nx, dx), "x_unit": ax.get("unit"),
            "y_name": ay.get("name") or _formula(names, ny, dy), "y_unit": ay.get("unit"),
            "cross_formula": f"по горизонтали {_formula(names, nx, dx)}; по вертикали {_formula(names, ny, dy)}"}
    if not days:
        return {**base, "points": [], "no_data": "Формы не совпали ни по одному отделению и дню — сравнить нечего."}
    use = set(_span_days(days, sc, from_date, to_date))
    xs: dict = defaultdict(list)
    ys: dict = defaultdict(list)
    for (d, r), p in px.items():
        if d in use and (d, r) in py:  # точка — только где есть ОБА показателя за тот же день
            xs[r].append(p)
            ys[r].append(py[(d, r)])
    pts = [{"label": r, "x": _ratio(xs[r]), "y": _ratio(ys[r]), "days": len(xs[r])} for r in xs]
    pts = [p for p in pts if p["x"] is not None and p["y"] is not None]
    mx, my = _median([p["x"] for p in pts]), _median([p["y"] for p in pts])
    counts: dict = defaultdict(int)
    for p in pts:
        q = ("hi" if p["x"] > mx else "lo", "hi" if p["y"] > my else "lo")
        p["quadrant"] = "-".join(q)
        counts[q] += 1
    norm_line = None
    nf = ay.get("norm_field")
    if nf:
        from ._norms import field_norms
        code = next((x["dataset_code"] for x in ny if x["field"] == nf), None)
        if code:
            f = (await field_norms(conn, org_id, code)).get(nf) or {}
            n = f.get("norm") or {}
            norm_line = {k: n.get(k) for k in ("warn", "danger") if n.get(k) is not None} or None
    span = sorted(use)
    return {**base, "points": sorted(pts, key=lambda p: -p["y"]), "x_median": mx, "y_median": my,
            "norm_lines": norm_line, "as_of": span[-1].isoformat(),
            "quadrants": [{"key": "-".join(q), "count": counts[q], "text": QUADRANTS[q]}
                          for q in (("hi", "hi"), ("lo", "hi"), ("hi", "lo"), ("lo", "lo"))],
            "cross_note": (f"{_span_text(span)} · {len(pts)} {_pl(len(pts))}; черты — медианы: "
                           "половина отделений по каждую сторону")}


def _pl(n: int) -> str:
    from ...plural import plural
    return plural(n, "отделение", "отделения", "отделений")


# --- Готовые показатели и страница «Между формами» --------------------------

CROSS_PAGE = "Между формами"

# Графы ищутся по смыслу имени, а не по коду: код у каждой формы свой, а
# «Количество работающих окон» и «Всего выдано талонов» называются одинаково
# в любом файле этой формы.
_PATTERNS = {
    "tickets": ("талон",),
    "windows": ("работающих окон",),
    "hours": ("рабочих часов",),
    "wait": ("среднее время ожидания",),
    "service": ("среднее время обслуживания",),
    "accepted": ("итого", "принято"),
}


async def _find_fields(conn, org_id) -> dict:
    """{смысл → {dataset_code, field, name}}: первое совпадение по каждой роли.
    Для «принято» — свод формы («ИТОГО · Принято»), а не одна услуга."""
    rows = await conn.fetch(
        "select distinct on (cf.object_id, cf.code) dr.code as ds, cf.code, cf.name, cf.unit "
        "from canonical_fields cf join dataset_releases dr on dr.object_id = cf.object_id "
        "where dr.organization_id=$1 and dr.status <> 'superseded' and cf.data_type='number' "
        "order by cf.object_id, cf.code", org_id)
    out: dict = {}
    for r in rows:
        low = (r["name"] or "").lower()
        for role, words in _PATTERNS.items():
            if role in out:
                continue
            if role == "accepted":
                if low.startswith("итого") and "принято" in low:
                    out[role] = {"dataset_code": r["ds"], "field": r["code"], "name": r["name"]}
            elif all(w in low for w in words):
                out[role] = {"dataset_code": r["ds"], "field": r["code"], "name": r["name"], "unit": r["unit"]}
    return out


def _p(f: dict) -> dict:
    return {"dataset_code": f["dataset_code"], "field": f["field"]}


async def presets(conn, org_id) -> list:
    """Показатели между формами, для которых в системе нашлись графы."""
    f = await _find_fields(conn, org_id)
    out = []

    def add(key, name, num, den, unit=None, bind=None, hint=""):
        if all(x in f for x in num + den):
            out.append({"key": key, "name": name, "unit": unit, "hint": hint,
                        "cross": {"num": [_p(f[x]) for x in num], "den": [_p(f[x]) for x in den],
                                  "unit": unit,
                                  **({"norm_field": f[bind]["field"]} if bind and bind in f else {})},
                        # К какой графе привязан виджет: по ней применяется порог
                        # показателя (у взвешенного ожидания — порог ожидания).
                        "bind": _p(f[bind]) if bind and bind in f else _p(f[num[0]])})

    add("tickets_per_window", "Талонов на окно", ["tickets"], ["windows"],
        hint="сколько посетителей пришлось на одно работающее окно за день")
    add("tickets_per_window_hour", "Талонов на окно-час", ["tickets"], ["windows", "hours"],
        hint="нагрузка на окно с учётом часов работы отделения")
    add("accepted_per_window", "Принято обращений на окно", ["accepted"], ["windows"],
        hint="обращения из ежедневного отчёта на одно работающее окно")
    add("wait_weighted", "Среднее ожидание, взвешенное по талонам", ["wait", "tickets"], ["tickets"],
        unit="мин", bind="wait",
        hint="ожидание по республике, где отделение с большим потоком весит больше")
    add("service_weighted", "Среднее обслуживание, взвешенное по талонам", ["service", "tickets"], ["tickets"],
        unit="мин", bind="service",
        hint="время обслуживания по республике с учётом потока посетителей")
    return out


def cross_page_specs(found: list) -> list:
    """Виджеты страницы «Между формами»: карточки всех показателей, рейтинг
    нагрузки на окно-час и динамика нагрузки и взвешенного ожидания."""
    specs, y = [], 0

    def w(name, wtype, p, extra=None):
        nonlocal y
        cfg = {"cross": p["cross"], "dataset_code": p["bind"]["dataset_code"],
               "value_field": p["bind"]["field"], **({"unit": p["unit"]} if p["unit"] else {}),
               **(extra or {})}
        specs.append({"name": name, "widget_type": wtype, "config": cfg, "position_x": 0,
                      "position_y": y, "width": 3 if wtype == "kpi" else 12,
                      "height": 3 if wtype == "kpi" else 7})
        y += 1

    by = {p["key"]: p for p in found}
    for p in found:
        w(p["name"], "kpi", p)
    # Рейтинг — только по нагрузке: взвешенное ожидание отделения за один день
    # совпадает с его обычным средним, и рейтинг повторил бы соседний виджет.
    if "tickets_per_window_hour" in by:
        p = by["tickets_per_window_hour"]
        # За неделю, а не за один день: день отделения — шум (отпуск, сбой).
        w(f"{p['name']}: по отделениям за неделю", "ranked", p,
          {"top_n": 10, "cross": {**p["cross"], "span": "7"}})
    if "tickets_per_window_hour" in by and "wait_weighted" in by:
        lx, ly = by["tickets_per_window_hour"], by["wait_weighted"]
        specs.append({"name": "Нагрузка на окно-час и ожидание: где очередь от нехватки окон",
                      "widget_type": "scatter", "position_x": 0, "position_y": y, "width": 12, "height": 9,
                      "config": {"scatter": {
                          "x": {**lx["cross"], "name": lx["name"]},
                          "y": {**ly["cross"], "name": ly["name"]},
                          "span": "7"}}})
        y += 1
    for key in ("tickets_per_window_hour", "wait_weighted"):
        if key in by:
            w(f"Динамика: {by[key]['name'].lower()}", "dynamics", by[key])
    return specs


async def build_cross_page(conn, org_id, user_id, dashboard_id: str) -> dict:
    """Добавить к дашборду страницу «Между формами». Повтор заменяет наполнение
    только этой страницы — как у страницы лестницы."""
    from . import service as svc
    from ._suggest import AUTO_LAYOUT_MODE

    found = await presets(conn, org_id)
    if not found:
        raise DashboardError("В системе нет форм, между которыми можно посчитать показатели: "
                             "нужны графы «работающих окон», «талонов» или «ИТОГО · Принято»")
    specs = cross_page_specs(found)
    pid = await conn.fetchval("select id from dashboard_pages where dashboard_id=$1::uuid and name=$2",
                              dashboard_id, CROSS_PAGE)
    if pid:
        await conn.execute("delete from widgets where page_id=$1::uuid", str(pid))
        pid = str(pid)
    else:
        page = await svc.create_page(conn, org_id, user_id, dashboard_id, CROSS_PAGE, None, AUTO_LAYOUT_MODE)
        pid = str(page["id"])
    for s in specs:
        await svc.create_widget(conn, org_id, user_id, pid, s["name"], s["widget_type"], s["config"],
                                {"position_x": s["position_x"], "position_y": s["position_y"],
                                 "width": s["width"], "height": s["height"]})
    return {"page_id": pid, "page": CROSS_PAGE, "widgets": len(specs),
            "indicators": [p["name"] for p in found]}
