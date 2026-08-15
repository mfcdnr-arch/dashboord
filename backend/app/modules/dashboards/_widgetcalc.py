"""Расчёт данных виджета по типу (вынесено из _widgetdata.py): _compute_widget —
диспетчер по widget_type (kpi/gauge/plan_fact/графики/матрицы/аннотации) + вспомогательная
статистика (цель/тренд/аномалии, без ИИ). Читает данные через _widgetsources,
не знает о кэше/RLS-на-дашборд/HTTP — это забота _widgetdata.
"""
from __future__ import annotations

import math
import statistics
from typing import Dict, List, Optional

from ._alerts import evaluate_alert
from ._base import DashboardError
from ._rowrls import allowed_rows_for_dataset
from ._widgetsources import (
    _dataset_as_of,
    _dataset_multi_series,
    _dataset_period_series,
    _dataset_series,
    _dataset_table,
    _formula_value,
    _metric_value,
)


def _apply_target(res: dict, cfg: dict, value) -> None:
    """Цель/бенчмарк на показателе (KPI/gauge): добавляет target и % достижения."""
    t = cfg.get("target")
    if t is None or value is None:
        return
    try:
        tgt = float(t)
    except (TypeError, ValueError):
        return
    res["target"] = tgt
    res["target_label"] = cfg.get("target_label") or "Цель"
    res["target_pct"] = (float(value) / tgt * 100.0) if tgt else None


def _nice_ceiling(v: float) -> float:
    """Верх шкалы — круглое число: деления спидометра должны читаться."""
    if v <= 0:
        return 100
    step = 50 if v <= 1000 else 10 ** (len(str(int(v))) - 1)
    return math.ceil(v / step) * step


def _linear_trend(values: list) -> Optional[dict]:
    """Линейная регрессия y=a+b·x (x=0..n-1) по ряду значений (без ИИ, метод
    наименьших квадратов). Возвращает наклон и концы прямой для наложения."""
    ys = [v for v in values if v is not None]
    n = len(ys)
    if n < 2:
        return None
    xs = range(n)
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * ys[x] for x in xs)
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    b = (n * sxy - sx * sy) / denom
    a = (sy - b * sx) / n
    return {"slope": b, "endpoints": [a, a + b * (len(values) - 1)], "intercept": a}


def _detect_anomalies(periods: list, values: list, threshold: float = 2.0) -> list:
    """Волна F: простое обнаружение аномалий БЕЗ ИИ — точки ряда, отклонившиеся
    от линии линейного тренда (метод наименьших квадратов, та же `_linear_trend`,
    что и для наложения на график) больше чем на `threshold` стандартных
    отклонений остатков. Нужно ≥3 точек (на 2 точках тренд проходит точно через
    обе, остатков нет — «аномалий» не бывает по определению)."""
    n = len(values)
    if n < 3 or any(v is None for v in values):
        return []
    trend = _linear_trend(values)
    if not trend:
        return []
    a, b = trend["intercept"], trend["slope"]
    residuals = [values[i] - (a + b * i) for i in range(n)]
    std = statistics.pstdev(residuals)
    if std == 0:
        return []
    out = []
    for i, r in enumerate(residuals):
        dev = r / std
        if abs(dev) > threshold:
            out.append({"index": i, "period": periods[i] if i < len(periods) else None,
                        "value": values[i], "expected": round(a + b * i, 2), "deviation": round(dev, 2)})
    return out


def _normalize_cfg(cfg: dict) -> dict:
    """Сглаживает историческое расхождение ключей конфигурации виджетов.

    Одни типы описывают поле как `value_field` (одно поле: kpi/bar/line/pie/…),
    другие — как `value_fields` (набор: compare/heatmap/pivot). Пользователи и
    внешние вызовы API регулярно путают формы, получая «укажите value_fields»
    на, казалось бы, заполненной форме. Принимаем обе и достраиваем недостающую,
    не меняя того, что хранится в БД.
    """
    if not isinstance(cfg, dict):
        return cfg
    one, many = cfg.get("value_field"), cfg.get("value_fields")
    if one and not many:
        cfg = {**cfg, "value_fields": [one]}
    elif many and not one:
        first = many[0] if isinstance(many, (list, tuple)) and many else None
        if first:
            cfg = {**cfg, "value_field": first}
    return cfg


async def _compute_widget(conn, org_id, t: str, name: str, cfg: dict,
                          from_date=None, to_date=None, row=None, user=None) -> dict:
    cfg = _normalize_cfg(cfg)
    # Виджетный фильтр (переопределение глобального): если у виджета задан
    # собственный фильтр (filter_scope='own'), он игнорирует фильтр страницы.
    if cfg.get("filter_scope") == "own":
        from_date = cfg.get("own_from") or None
        to_date = cfg.get("own_to") or None
        row = cfg.get("own_row") or None

    # Row-level RLS: разрешённые строки датасета для пользователя (None — все).
    # Применяется к ВИДЖЕТНЫМ чтениям датасета; именованные метрики/формулы —
    # не фильтруются (их значения объективны). user=None (предпросмотр) → все строки.
    allowed = None
    if user is not None and cfg.get("dataset_code"):
        allowed = await allowed_rows_for_dataset(conn, org_id, user, cfg["dataset_code"])

    # Закреплённый период: виджет читает выпуск ЗА ЭТУ дату, а не последний.
    # Так устроены страницы «по неделям» — они показывают срез и не меняются,
    # когда приходит следующая неделя.
    period = cfg.get("period") or None

    if t == "text":
        return {"type": "text", "title": name, "heading": cfg.get("heading"),
                "body": cfg.get("body"), "align": cfg.get("align", "left")}

    if t == "image":
        return {"type": "image", "title": name, "url": cfg.get("url"),
                "caption": cfg.get("caption"), "fit": cfg.get("fit", "contain")}

    if t == "compare":
        fields = cfg.get("value_fields") or []
        if not cfg.get("dataset_code") or not fields:
            raise DashboardError("Сравнение: укажите dataset_code и value_fields")
        res = await _dataset_multi_series(conn, org_id, cfg["dataset_code"], fields, row, allowed, period)
        res["type"], res["viz"], res["title"] = "compare", cfg.get("viz", "bar"), name
        # Шкала: 'log' | 'linear' | не задано (тогда решает разброс значений на
        # фронте). Показатели одной формы различаются на два порядка — на линейной
        # шкале маленькие столбики вырождаются в полоску у нуля.
        if cfg.get("scale"):
            res["scale"] = cfg["scale"]
        return res

    if t == "heatmap":
        # Тепловая карта: матрица строки(датасета) × поля, значение — интенсивность цвета.
        # Для МФЦ удобно: услуги × периоды/отделы, нагрузка по строкам и столбцам.
        fields = cfg.get("value_fields") or []
        if not cfg.get("dataset_code") or not fields:
            raise DashboardError("Тепловая карта: укажите dataset_code и value_fields")
        ms = await _dataset_multi_series(conn, org_id, cfg["dataset_code"], fields, row, allowed, period)
        # ms: {categories:[строки], series:[{name:поле, data:[значения по строкам]}]}
        cols = [s["name"] for s in ms["series"]]
        cells = []  # [col_idx, row_idx, value]
        nums = []
        for ci, s in enumerate(ms["series"]):
            for ri, v in enumerate(s["data"]):
                if v is not None:
                    cells.append([ci, ri, v])
                    nums.append(v)
        return {"type": "heatmap", "title": name, "rows": ms["categories"], "columns": cols,
                "cells": cells, "min": (min(nums) if nums else 0), "max": (max(nums) if nums else 0)}

    if t == "pivot":
        # Сводная таблица: строки × поля + итоги по строкам, столбцам и общий.
        # Для МФЦ: услуги × показатели с автоматическими суммами (отчётность).
        fields = cfg.get("value_fields") or []
        if not cfg.get("dataset_code") or not fields:
            raise DashboardError("Сводная таблица: укажите dataset_code и value_fields")
        ms = await _dataset_multi_series(conn, org_id, cfg["dataset_code"], fields, row, allowed, period)
        cols = [s["name"] for s in ms["series"]]
        col_totals = [0.0] * len(cols)
        grand = 0.0
        rows_out = []
        for ri, rlabel in enumerate(ms["categories"]):
            vals, rtotal = [], 0.0
            for ci, s in enumerate(ms["series"]):
                v = s["data"][ri]
                vals.append(v)
                if v is not None:
                    rtotal += v
                    col_totals[ci] += v
                    grand += v
            rows_out.append({"row": rlabel, "values": vals, "total": rtotal})
        return {"type": "pivot", "title": name, "columns": cols, "rows": rows_out,
                "col_totals": col_totals, "grand_total": grand}

    if t == "waterfall":
        # Водопад: вклад каждой строки в накопленный итог (нарастающим), финальный столбец «Итого».
        # Для МФЦ: из чего складывается общий объём (услуги → суммарно).
        if not cfg.get("dataset_code") or not cfg.get("value_field"):
            raise DashboardError("Водопад: укажите dataset_code и value_field")
        series = await _dataset_series(conn, org_id, cfg["dataset_code"], cfg["value_field"], row, allowed, period)
        cats = [s["category"] for s in series]
        vals = [s["value"] for s in series]
        return {"type": "waterfall", "title": name, "categories": cats, "values": vals,
                "total_label": cfg.get("total_label") or "Итого"}

    if t == "objects_compare":
        # Сравнение подразделений: показатель (поле) агрегируется по ОБЪЕКТАМ
        # (каждый объект = подразделение/филиал), берётся последний выпуск на объект.
        field = cfg.get("value_field")
        if not field:
            raise DashboardError("Сравнение подразделений: укажите показатель (поле)")
        rows = await conn.fetch(
            "with latest as ("
            "  select distinct on (object_id) id, object_id from dataset_releases "
            "  where organization_id=$1 and status<>'superseded' and object_id is not null "
            "  order by object_id, reporting_period_start desc nulls last, created_at desc) "
            "select o.name as obj, coalesce(sum(dv.value_number),0) as val "
            "from latest l join objects o on o.id=l.object_id "
            "join dataset_values dv on dv.dataset_release_id=l.id and dv.canonical_field_code=$2 "
            "group by o.name having coalesce(sum(dv.value_number),0) <> 0 order by val desc",
            org_id, field)
        return {"type": "objects_compare", "title": name,
                "categories": [r["obj"] for r in rows], "values": [float(r["val"]) for r in rows]}

    if t == "cross_dataset_compare":
        # Сравнение источников: несколько РАЗНЫХ dataset_code (разных загруженных
        # файлов) на одном графике — без формул, только выбором датасет+поле.
        # Сопоставление по строке (row_label) или по периоду (месяц выпуска —
        # бакетирование по YYYY-MM, а не точная дата: у разных файлов выпуски
        # редко датируются день-в-день, месяц — устойчивый общий знаменатель).
        items = cfg.get("series") or []
        if len(items) < 2:
            raise DashboardError("Сравнение источников: укажите минимум 2 источника (датасет + поле)")
        match_by = cfg.get("match_by") or "row_label"
        cat_order: List[str] = []
        seen_cat: set = set()
        raw_series = []
        sources_meta = []  # свежесть каждого источника — единой даты у виджета нет
        for it in items:
            dc, vf = it.get("dataset_code"), it.get("value_field")
            if not dc or not vf:
                raise DashboardError("Сравнение источников: у каждого источника укажите датасет и поле")
            label = it.get("label") or f"{dc}.{vf}"
            item_allowed = await allowed_rows_for_dataset(conn, org_id, user, dc) if user is not None else None
            if match_by == "period":
                pairs = await _dataset_period_series(conn, org_id, dc, vf, from_date, to_date, row, item_allowed)
                vmap: Dict[str, float] = {}
                for period, val in pairs:
                    bucket = period[:7] if len(period) >= 7 else period  # YYYY-MM
                    vmap[bucket] = vmap.get(bucket, 0.0) + val
            else:
                vmap = {p["category"]: p["value"]
                        for p in await _dataset_series(conn, org_id, dc, vf, row, item_allowed)}
            for c in vmap:
                if c not in seen_cat:
                    seen_cat.add(c)
                    cat_order.append(c)
            raw_series.append((label, vmap))
            sources_meta.append({"label": label, "dataset_code": dc, "as_of": await _dataset_as_of(conn, org_id, dc)})
        categories = sorted(cat_order)
        series = [{"name": label, "data": [vmap.get(c) for c in categories]} for label, vmap in raw_series]
        return {"type": "cross_dataset_compare", "title": name, "viz": cfg.get("viz", "bar"),
                "scale": cfg.get("scale"),
                "categories": categories, "series": series, "match_by": match_by, "sources": sources_meta}

    if t == "dynamics":
        if not cfg.get("dataset_code") or not cfg.get("value_field"):
            raise DashboardError("Динамика: укажите dataset_code и value_field")
        series = await _dataset_period_series(
            conn, org_id, cfg["dataset_code"], cfg["value_field"], from_date, to_date, row, allowed)
        periods = [p for p, _ in series]
        values = [v for _, v in series]
        change = values[-1] - values[-2] if len(values) >= 2 else None
        change_pct = (change / values[-2] * 100.0) if (change is not None and values[-2]) else None
        res = {"type": "dynamics", "title": name, "periods": periods, "values": values,
               "change": change, "change_pct": change_pct}
        if len(values) >= 2:
            # К какой ПАРЕ дат относится «к пред. периоду»: когда точек больше двух,
            # по одному числу не понять, между чем и чем прирост.
            res["change_from_period"], res["change_to_period"] = periods[-2], periods[-1]
            # Итог за весь показанный отрезок: от первой даты к последней. Считается
            # от текущего ряда, поэтому новый выпуск данных пересчитывает его сам.
            total = values[-1] - values[0]
            res["total_change"] = total
            res["total_change_pct"] = (total / values[0] * 100.0) if values[0] else None
            res["first_period"], res["last_period"] = periods[0], periods[-1]
            res["first_value"], res["last_value"] = values[0], values[-1]
            res["periods_count"] = len(values)
        if cfg.get("trend"):
            tr = _linear_trend(values)
            if tr:
                res["trend"], res["trend_slope"] = tr["endpoints"], tr["slope"]
        if cfg.get("anomalies"):
            threshold = float(cfg.get("anomaly_threshold") or 2.0)
            res["anomaly_threshold"] = threshold
            res["anomalies"] = _detect_anomalies(periods, values, threshold)
        res["alert"] = evaluate_alert("dynamics", cfg, res)
        return res

    if t == "yoy":
        # Год к году: помесячные ряды последнего года данных против предыдущего.
        # Глобальный фильтр периода НЕ применяется (сравнение всегда «последний
        # год против прошлого»); cross-filter «Строка» и row-RLS — применяются.
        if not cfg.get("dataset_code") or not cfg.get("value_field"):
            raise DashboardError("Год к году: укажите dataset_code и value_field")
        series = await _dataset_period_series(conn, org_id, cfg["dataset_code"], cfg["value_field"], None, None, row, allowed)
        by_year: Dict[int, Dict[int, float]] = {}
        for p, v in series:
            if len(p) < 7 or not p[:4].isdigit():
                continue  # выпуски без даты периода в сравнении не участвуют
            y, m = int(p[:4]), int(p[5:7])
            ym = by_year.setdefault(y, {})
            ym[m] = ym.get(m, 0.0) + v
        if not by_year:
            raise DashboardError("Год к году: у выпусков датасета нет дат периодов")
        cur = max(by_year)
        prev = cur - 1
        months = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
        cur_map, prev_map = by_year.get(cur, {}), by_year.get(prev, {})
        cur_vals = [cur_map.get(m) for m in range(1, 13)]
        prev_vals = [prev_map.get(m) for m in range(1, 13)]
        cur_total = sum(v for v in cur_vals if v is not None)
        # Честное сравнение — по СОПОСТАВИМЫМ месяцам (данные есть в обоих годах),
        # иначе неполный год сравнивался бы с полным.
        common = sorted(set(cur_map) & set(prev_map))
        if common:
            s_prev = sum(prev_map[m] for m in common)
            s_cur = sum(cur_map[m] for m in common)
            diff = s_cur - s_prev
            pct = (diff / s_prev * 100.0) if s_prev else None
            yoy_change: Optional[float] = diff
            yoy_change_pct: Optional[float] = pct
        else:
            yoy_change = yoy_change_pct = None
        return {"type": "yoy", "title": name, "months": months,
                "current_year": cur, "previous_year": prev if prev_map else None,
                "current": cur_vals, "previous": prev_vals,
                "current_total": cur_total,
                "previous_total": (sum(v for v in prev_vals if v is not None) if prev_map else None),
                "compared_months": len(common),
                "change": yoy_change, "change_pct": yoy_change_pct, "unit": cfg.get("unit")}

    if t == "kpi":
        if cfg.get("formula"):
            value, unit = await _formula_value(conn, org_id, cfg["formula"]), cfg.get("unit")
        elif cfg.get("metric_code"):
            value, unit = await _metric_value(conn, org_id, cfg["metric_code"])
        elif cfg.get("dataset_code") and cfg.get("value_field"):
            series = await _dataset_series(conn, org_id, cfg["dataset_code"], cfg["value_field"], row, allowed, period)
            value, unit = sum(s["value"] for s in series), cfg.get("unit")
        else:
            raise DashboardError("KPI: укажите формулу, metric_code или dataset_code+value_field")
        res = {"type": "kpi", "value": value, "unit": unit, "title": name}
        # Два необязательных украшения, которые превращают голое число в
        # показатель: прирост к прошлому отчёту и мини-график по периодам.
        # Оба ВЫКЛЮЧЕНЫ по умолчанию — это лишние запросы, а на странице
        # карточек бывает полтора десятка.
        if cfg.get("dataset_code") and cfg.get("value_field") and (cfg.get("compare_prev") or cfg.get("spark")):
            trend = await _dataset_period_series(
                conn, org_id, cfg["dataset_code"], cfg["value_field"], None, None, row, allowed)
            if cfg.get("spark") and len(trend) > 1:
                res["spark"] = [v for _p, v in trend]
                res["spark_periods"] = [p for p, _v in trend]
            if cfg.get("compare_prev") and len(trend) > 1:
                prev_period, prev_value = trend[-2]
                res["prev_value"], res["prev_period"] = prev_value, prev_period
                res["delta"] = value - prev_value
                res["delta_pct"] = (
                    round((value - prev_value) / prev_value * 100, 2) if prev_value else None)
        _apply_target(res, cfg, value)
        res["alert"] = evaluate_alert("kpi", cfg, res)
        return res

    if t == "gauge":
        # Спидометр: значение как у KPI + шкала (max). Идеален для «% выполнения».
        if cfg.get("formula"):
            value, unit = await _formula_value(conn, org_id, cfg["formula"]), cfg.get("unit")
        elif cfg.get("metric_code"):
            value, unit = await _metric_value(conn, org_id, cfg["metric_code"])
        elif cfg.get("dataset_code") and cfg.get("value_field"):
            series = await _dataset_series(conn, org_id, cfg["dataset_code"], cfg["value_field"], row, allowed, period)
            value, unit = sum(s["value"] for s in series), cfg.get("unit")
        else:
            raise DashboardError("Gauge: укажите формулу, metric_code или dataset_code+value_field")
        gmax = cfg.get("gauge_max")
        if gmax is None:
            if unit and "%" in unit:
                # Обычная шкала процента — 100. Но выполнение плана бывает и
                # 187 %, и 656 %: при жёстком потолке стрелка упиралась бы в
                # край, и перевыполнение выглядело бы как «ровно предел».
                gmax = 100 if (value or 0) <= 100 else _nice_ceiling(float(value) * 1.1)
            else:
                gmax = round((value or 0) * 1.25) or 100
        res = {"type": "gauge", "value": value, "unit": unit, "max": gmax, "title": name}
        _apply_target(res, cfg, value)
        res["alert"] = evaluate_alert("kpi", cfg, res)  # те же пороги, что и KPI
        return res

    if t == "plan_fact":
        if cfg.get("plan_metric") and cfg.get("fact_metric"):
            plan, unit = await _metric_value(conn, org_id, cfg["plan_metric"])
            fact, _ = await _metric_value(conn, org_id, cfg["fact_metric"])
        elif cfg.get("dataset_code") and cfg.get("plan_field") and cfg.get("fact_field"):
            plan = sum(s["value"] for s in await _dataset_series(
                conn, org_id, cfg["dataset_code"], cfg["plan_field"], row, allowed, period))
            fact = sum(s["value"] for s in await _dataset_series(
                conn, org_id, cfg["dataset_code"], cfg["fact_field"], row, allowed, period))
            unit = cfg.get("unit")
        else:
            raise DashboardError("План-факт: укажите plan_metric+fact_metric или dataset_code+plan_field+fact_field")
        pct = (fact / plan * 100.0) if plan else None
        res = {"type": "plan_fact", "plan": plan, "fact": fact, "delta": fact - plan, "pct": pct, "unit": unit, "title": name}
        res["alert"] = evaluate_alert("plan_fact", cfg, res)
        return res

    if t == "table":
        if not cfg.get("dataset_code"):
            raise DashboardError("Таблица: укажите dataset_code")
        table = await _dataset_table(conn, org_id, cfg["dataset_code"], row, allowed, period)
        return {"type": "table", "title": name, **table}

    # bar | line | pie
    if not cfg.get("dataset_code") or not cfg.get("value_field"):
        raise DashboardError("График: укажите dataset_code и value_field")
    series = await _dataset_series(conn, org_id, cfg["dataset_code"], cfg["value_field"], row, allowed, period)
    return {"type": t, "title": name,
            "categories": [s["category"] for s in series],
            "values": [s["value"] for s in series]}
