"""Расчёт данных виджета по типу (вынесено из _widgetdata.py): _compute_widget —
диспетчер по widget_type (kpi/gauge/plan_fact/графики/матрицы/аннотации) + вспомогательная
статистика (цель/тренд/аномалии, без ИИ). Читает данные через _widgetsources,
не знает о кэше/RLS-на-дашборд/HTTP — это забота _widgetdata.
"""
from __future__ import annotations

import math
import statistics
from typing import Dict, List, Optional

from ._aggregate import aggregate_series
from ._alerts import alert_styles, cell_alert_levels, evaluate_alert
from ._base import DashboardError, ru_date
from ._rowrls import allowed_rows_for_dataset
from ._widgetsources import (
    _align,
    _dataset_as_of,
    _dataset_field_period_matrix,
    _dataset_multi_series,
    _dataset_period_series,
    _dataset_row_period_matrix,
    _dataset_series,
    _dataset_table,
    _field_title,
    _field_titles,
    _formula_value,
    _metric_value,
    _prev_period,
)


async def _add_ghost(conn, org_id, cfg: dict, res: dict, row, allowed, period) -> None:
    """«Призрачная» линия прошлого отчёта поверх графика по строкам (п. 3).

    График по строкам показывает СРЕЗ одного отчёта: сколько у каждого района
    сейчас. Вопрос «а было сколько?» он не закрывает — за ответом человек шёл
    в «Динамику» или открывал прошлую неделю фильтром и сравнивал по памяти.
    Бледная серия позади текущей отвечает на него на месте.

    Три решения, важных для правильности:

    **Призрак читается ТЕМ ЖЕ кодом, что и сам виджет** (`_dataset_series` /
    `_dataset_multi_series` с другой датой) и с тем же набором разрешённых
    строк: иначе прошлый период считался бы по своим правилам и мог показать
    строки, которых человеку видеть нельзя.

    **Сопоставление по названию строки**, а не по номеру — см. `_align`.

    **Молчать нельзя.** Если прошлого отчёта нет вовсе или ни одна строка не
    сошлась, галочка включена, а на графике ничего не появляется — это выглядит
    поломкой. Поэтому вместо призрака возвращается причина словами.

    🔴 **У «Сравнения» призрака НЕТ — и это решение, а не пропуск.** Сначала он
    там был, но замер отрисовки показал, чем это кончается: у виджета заказчика
    13 показателей в ОДНОЙ категории, призрак удваивает число столбиков до 26, а
    `barGap` в ECharts действует на всю группу серий сразу и совместить их
    попарно не может — бледные столбики встали отдельной кучей СЛЕВА от текущих
    (замерено: призраки на x 85…270, текущие на 278…470), то есть получился
    частокол из 26 полосок по 11px вместо ответа «как было». На вопрос «как
    изменились все показатели разом» уже отвечают матрица «показатель × дата» и
    карточки-группы с приростом на каждый разрез — они делают это лучше.
    """
    if not cfg.get("ghost_prev") or not cfg.get("dataset_code"):
        return
    prev = await _prev_period(conn, org_id, cfg["dataset_code"], period)
    if prev is None:
        res["ghost_note"] = "Это первый отчёт по этим данным — сравнивать не с чем."
        return

    cats = res.get("categories") or []
    prev_rows = await _dataset_series(conn, org_id, cfg["dataset_code"], cfg["value_field"],
                                      row, allowed, prev)
    values, matched = _align(cats, prev_rows)
    if not matched:
        res["ghost_note"] = (f"Отчёт за {ru_date(prev)} не сопоставился с текущим "
                             "ни по одной строке — показывать нечего.")
        return
    res["ghost"] = {"period": prev, "values": values}


async def _column_value(conn, org_id, cfg: dict, field: str, row, allowed, period):
    """Одно число по столбцу датасета: сумма количеств, среднее у долей.

    Возвращает (значение, способ, число строк): способ и число строк нужны
    карточке, чтобы подписать «среднее по N строкам», — среднее по долям это
    приближение, и выдавать его за точный итог нельзя.
    """
    series = await _dataset_series(conn, org_id, cfg["dataset_code"], field, row, allowed, period)
    title = await _field_title(conn, org_id, cfg["dataset_code"], field, period)
    value, how = aggregate_series((s["value"] for s in series), title, cfg.get("unit"))
    return value, how, len(series)


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


# «Полосы план-факт»: сколько пар показываем и как выбираем общую шкалу.
# Потолок пар — чтобы карточка не превратилась в таблицу без заголовков;
# шкала снизу не ниже 120 % (иначе выполненный план упирается в самый край и
# «выполнено» неотличимо от «перевыполнено»), сверху не выше 300 % (при 656 %
# у одной строки остальные схлопнулись бы в невидимые огрызки).
BULLET_MAX_PAIRS = 12
BULLET_SCALE_MIN = 120.0
BULLET_SCALE_CAP = 300.0


def _as_date(v):
    """Дата из ISO-строки или объекта даты; мусор — None, а не исключение.

    Срок термометра приходит из настройки виджета, то есть из того, что человек
    когда-то ввёл руками. Падать на нём всем виджетом нельзя — расчёт скажет,
    что срок не задан, и это чинится в форме.
    """
    from datetime import date, datetime

    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str) and len(v) >= 10:
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None


def _plan_forecast(series: list, plan, fact) -> dict:
    """Когда факт дорастёт до плана при нынешнем темпе (линейная экстраполяция).

    Темп берётся как средний прирост в ДЕНЬ между первым и последним отчётом
    ряда, а не между двумя последними: недельные формы приходят неровно
    («пятница/понедельник»), и пара соседних отчётов даёт то втрое больший, то
    втрое меньший темп. Средний по отрезку объясним человеку словами — «в
    среднем +N в день с 22.07 по 05.08», — и именно это пишется в подписи.

    Ответ всегда честный: «план уже выполнен», «при таком темпе план не будет
    достигнут» (темп ноль или вниз) или «данных мало» — вместо выдуманной даты.
    """
    from datetime import date, timedelta

    out: dict = {"reason": None, "date": None}
    if plan is None or fact is None:
        return {"reason": "no_data"}
    if fact >= plan:
        return {"reason": "done"}
    pts = [(p, v) for p, v in series if len(p) == 10 and p[:4].isdigit()]
    if len(pts) < 2:
        return {"reason": "few_points"}
    (p0, v0), (p1, v1) = pts[0], pts[-1]
    d0, d1 = date.fromisoformat(p0), date.fromisoformat(p1)
    days = (d1 - d0).days
    if days <= 0:
        return {"reason": "few_points"}
    rate = (v1 - v0) / days
    if rate <= 0:
        return {"reason": "no_growth", "rate": rate, "from_period": p0, "to_period": p1}
    remain = plan - fact
    need = remain / rate
    if need > 3650:
        # Десять лет — это не прогноз, а способ сказать «такими темпами никогда».
        return {"reason": "too_far", "rate": rate, "days": round(need),
                "from_period": p0, "to_period": p1}
    out = {"reason": "ok", "rate": rate, "days": int(round(need)),
           "date": (d1 + timedelta(days=int(round(need)))).isoformat(),
           "remain": remain, "from_period": p0, "to_period": p1, "points": len(pts)}

    # ── Насколько этой дате можно верить ─────────────────────────────────────
    # Средний темп по всему отрезку — устойчивая, но слепая к развороту оценка:
    # если последние недели идут медленнее (сезонный спад, исчерпание базы),
    # одна дата выглядит увереннее, чем есть на самом деле. Считаем ВТОРОЙ темп
    # — по последней паре отчётов — и, когда он заметно расходится со средним,
    # честно показываем не точку, а промежуток.
    if len(pts) >= 3:
        (pa, va), (pb, vb) = pts[-2], pts[-1]
        gap = (date.fromisoformat(pb) - date.fromisoformat(pa)).days
        if gap > 0:
            recent = (vb - va) / gap
            out["rate_recent"] = recent
            if recent <= 0:
                # Последний отчёт роста не дал вовсе: дата по среднему темпу
                # остаётся, но выдавать её за надёжную нельзя.
                out["stalled"] = True
            elif abs(recent - rate) / rate > 0.25:
                alt = remain / recent
                if alt <= 3650:
                    out["days_alt"] = int(round(alt))
                    out["date_alt"] = (d1 + timedelta(days=int(round(alt)))).isoformat()
                else:
                    out["alt_too_far"] = True
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


# Виджеты, которым нужен весь РЯД периодов, а не один выпуск: они получают
# диапазон как есть и сами разворачивают его во временную ось.
RANGE_TYPES = {"dynamics", "yoy", "cross_dataset_compare", "matrix"}


async def _period_for_range(conn, org_id, code: str, from_date, to_date):
    """Последний отчёт набора данных, попавший в выбранный диапазон.

    Отдельная функция, а не условие внутри запроса, потому что смысл здесь
    содержательный: «дашборд за июль» — это состояние на конец июля, то есть
    последний июльский отчёт. Возвращает None, если отчётов за период нет
    вовсе; подставлять вместо них свежие данные нельзя — именно так период и
    «не работал» раньше.
    """
    conds = ["organization_id=$1", "code=$2", "status <> 'superseded'",
             "reporting_period_start is not null"]
    args = [org_id, code]
    if from_date:
        args.append(from_date)
        conds.append(f"reporting_period_start >= ${len(args)}::text::date")
    if to_date:
        args.append(to_date)
        conds.append(f"reporting_period_start <= ${len(args)}::text::date")
    row = await conn.fetchval(
        f"select reporting_period_start from dataset_releases where {' and '.join(conds)} "
        "order by reporting_period_start desc, created_at desc limit 1", *args)
    return row.isoformat() if row is not None else None


# Как называются разрезы в разборе имён госформ (ingestion/quality.classify_slice).
_SLICE_RU = {"cumulative": "нарастающим итогом", "weekly": "за отчётную неделю",
             "other": "в своём разрезе"}


async def _slice_mismatch(conn, org_id, code: str, plan_field: str, fact_field: str,
                          period) -> Optional[str]:
    """Предупреждение, когда план и факт заданы в РАЗНЫХ разрезах.

    Разбор разреза уже живёт в проверках качества выпуска
    (`ingestion.quality.classify_slice`) — берём его, чтобы система не
    противоречила сама себе: то, что при выпуске названо «за неделю», не может
    на дашборде считаться накопительным.
    """
    plan_name = await _field_title(conn, org_id, code, plan_field, period)
    fact_name = await _field_title(conn, org_id, code, fact_field, period)
    return slice_note(plan_name, fact_name)


def slice_note(plan_name: Optional[str], fact_name: Optional[str]) -> Optional[str]:
    """Чистая половина правила выше — по ИМЕНАМ граф, без обращений к БД.

    Вынесена затем, что «полосы план-факт» показывают до десятка пар сразу:
    ходить в БД за именем каждой графы отдельно значило бы делать четыре
    запроса на строку. Имена там уже прочитаны одним запросом, а правило
    должно остаться ОДНО — иначе одна и та же пара получала бы предупреждение
    на полосе и не получала на карточке «План-факт».
    """
    from ..ingestion.quality import classify_slice

    if not plan_name or not fact_name:
        return None
    ps, fs = classify_slice(plan_name), classify_slice(fact_name)
    if ps == fs:
        return None
    # «Прочий» разрез у ПЛАНА — норма: план обычно задан на срок («до 1
    # сентября»), и сравнивать его с накопительным фактом правильно.
    if ps == "other" and fs == "cumulative":
        return None
    return (f"План задан {_SLICE_RU.get(ps, ps)}, факт — {_SLICE_RU.get(fs, fs)}: "
            "проценты выполнения сопоставимы не полностью.")


async def _compute_widget(conn, org_id, t: str, name: str, cfg: dict,
                          from_date=None, to_date=None, row=None, user=None) -> dict:
    """Фильтр «Период» страницы + расчёт виджета.

    🔴 До этого период действовал ТОЛЬКО на «Динамику» (и на сравнение
    источников по периодам). Карточка, спидометр, таблица, графики, план-факт,
    воронка, светофор читали последний выпуск и период игнорировали МОЛЧА:
    человек ставил июль, видел прежние числа и либо решал, что данных нет, либо
    — что хуже — принимал августовскую цифру за июльскую.

    Здесь диапазон сводится к КОНКРЕТНОМУ выпуску (последний отчёт, попавший в
    период) и подставляется тем же полем `period`, которым уже пользуются
    страницы-срезы. Поэтому каждый тип виджета менять не пришлось: механизм
    чтения «за дату» существовал с 15.08, им просто никто не пользовался из
    фильтра страницы.
    """
    cfg = _normalize_cfg(cfg)
    # Свой фильтр виджета перекрывает фильтр страницы — учитываем ДО поиска
    # выпуска, иначе виджет со своим периодом получил бы чужой.
    if cfg.get("filter_scope") == "own":
        from_date = cfg.get("own_from") or None
        to_date = cfg.get("own_to") or None

    applied = None
    if not cfg.get("period") and (from_date or to_date) and cfg.get("dataset_code") and t not in RANGE_TYPES:
        applied = await _period_for_range(conn, org_id, cfg["dataset_code"], from_date, to_date)
        if applied is None:
            # Молчаливый откат к свежим данным и был дефектом: честнее сказать,
            # что за выбранный период отчётов нет, чем показать цифру не за тот.
            return {"type": t, "title": name, "no_data_in_period": True,
                    "from_date": from_date, "to_date": to_date}
        cfg = {**cfg, "period": applied}

    res = await _compute_widget_inner(conn, org_id, t, name, cfg, from_date, to_date, row, user)
    if applied and isinstance(res, dict):
        # Дата, за которую данные показаны НА САМОМ ДЕЛЕ. Без неё карточка
        # подписалась бы датой последнего выпуска — то есть снова соврала бы.
        res.setdefault("as_of", applied)
        res["period_filtered"] = True
    return res


async def _compute_widget_inner(conn, org_id, t: str, name: str, cfg: dict,
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

    if t == "funnel":
        # Воронка: этапы процесса по ПОЛЯМ формы (обращения → отправлено →
        # доставлено → записались). Четыре карточки показывают четыре числа,
        # но не отвечают на главный вопрос — ГДЕ теряются люди; воронка
        # отвечает: у каждого этапа подписано, какая доля дошла с предыдущего.
        fields = cfg.get("value_fields") or []
        if not cfg.get("dataset_code") or len(fields) < 2:
            raise DashboardError("Воронка: укажите dataset_code и минимум два этапа (value_fields)")
        stages = []
        for f in fields:
            value, _how, _rows = await _column_value(conn, org_id, cfg, f, row, allowed, period)
            title = await _field_title(conn, org_id, cfg["dataset_code"], f, period)
            stages.append({"field": f, "name": title or f, "value": value})
        first = stages[0]["value"] or 0
        for i, st in enumerate(stages):
            prev = stages[i - 1]["value"] if i else None
            # Доля от предыдущего этапа — это и есть «сколько дошло»; доля от
            # первого показывает сквозные потери всей цепочки.
            st["pct_of_prev"] = (st["value"] / prev * 100.0) if i and prev else None
            st["pct_of_first"] = (st["value"] / first * 100.0) if first else None
            st["lost"] = (prev - st["value"]) if i and prev is not None else None
        return {"type": "funnel", "title": name, "stages": stages, "unit": cfg.get("unit")}

    if t == "status_grid":
        # «Светофор» по строкам: плитка на каждую строку формы (район, субъект,
        # отделение) с цветом по порогам. Таблица на два десятка строк требует
        # читать числа подряд; плитки отвечают на вопрос «у кого плохо» сразу.
        field = cfg.get("value_field")
        if not cfg.get("dataset_code") or not field:
            raise DashboardError("Светофор: укажите dataset_code и показатель")
        series = await _dataset_series(conn, org_id, cfg["dataset_code"], field, row, allowed, period)
        plan_by_row: Dict[str, float] = {}
        if cfg.get("plan_field"):
            plan_by_row = {s["category"]: s["value"] for s in await _dataset_series(
                conn, org_id, cfg["dataset_code"], cfg["plan_field"], row, allowed, period)}
        tiles: List[dict] = []
        for s in series:
            plan = plan_by_row.get(s["category"])
            pct = (s["value"] / plan * 100.0) if plan else None
            # Отставание/превышение — в единицах показателя, а не только в %:
            # «88,51 %» не говорит, это 40 штук не хватает или 4000. Знак
            # хранит смысл сам: минус — отставание, плюс — перевыполнение.
            delta = (s["value"] - plan) if plan is not None else None
            # Цвет берут ТЕ ЖЕ пороги, что и остальные виджеты: своя шкала
            # цветов рядом с общей означала бы, что красный на соседних
            # виджетах значит разное.
            measure = pct if pct is not None else s["value"]
            alert = evaluate_alert("kpi", cfg, {"value": measure})
            tiles.append({"label": s["category"], "value": s["value"], "plan": plan,
                          "pct": pct, "delta": delta, "level": (alert or {}).get("level"),
                          "color": (alert or {}).get("color")})
        return {"type": "status_grid", "title": name, "cells": tiles,
                "unit": cfg.get("unit"), "compared_to_plan": bool(plan_by_row)}

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
        if cfg.get("growth_index") and match_by == "period":
            # Ровно ради этого случая индекс и нужен: два источника разного
            # масштаба на одной оси. КАЖДЫЙ ряд нормируется на СВОЮ первую
            # точку — общая база сделала бы сравнение бессмысленным.
            for srs in series:
                base = next((v for v in srs["data"] if v), None)
                srs["data"] = ([round(v / base * 100.0, 2) if v is not None else None
                                for v in srs["data"]] if base else srs["data"])
        return {"type": "cross_dataset_compare", "title": name, "viz": cfg.get("viz", "bar"),
                "scale": cfg.get("scale"),
                "growth_index": bool(cfg.get("growth_index") and match_by == "period"),
                "categories": categories, "series": series, "match_by": match_by, "sources": sources_meta}

    if t == "kpi_group":
        # Группа разрезов ОДНОГО показателя одной карточкой.
        # В госформе у показателя обычно три столбца («нарастающим итогом»,
        # «нарастающим итогом (текущий месяц)», «за отчётную неделю»), и до сих
        # пор каждый занимал свою карточку: на «Обзоре» тринадцать карточек
        # оказывались четырьмя показателями, а экран — стеной одинаковых
        # заголовков, в которой имя весит больше самого числа.
        fields = cfg.get("value_fields") or []
        if not cfg.get("dataset_code") or not fields:
            raise DashboardError("Группа показателей: укажите dataset_code и разрезы (value_fields)")
        from ..metrics.data_suggestions import _clean, _split_name

        series = None
        if cfg.get("compare_prev"):
            series = {}
        lines: List[dict] = []
        subject = None
        for f in fields:
            value, how, rows_used = await _column_value(conn, org_id, cfg, f, row, allowed, period)
            title = await _field_title(conn, org_id, cfg["dataset_code"], f, period) or f
            parts = _split_name(title)
            subject = subject or _clean(parts["subject"])
            # Подпись строки — РАЗРЕЗ показателя: имя показателя стоит в
            # заголовке карточки, повторять его в каждой строке незачем.
            label = _clean(parts["slice"]) or _clean(parts["role"]) or title
            line = {"field": f, "label": label, "name": title, "value": value}
            if how == "avg" and rows_used > 1:
                line["aggregate"], line["rows_used"] = how, rows_used
            if cfg.get("compare_prev"):
                trend = await _dataset_period_series(
                    conn, org_id, cfg["dataset_code"], f, None, period, row, allowed)
                if len(trend) > 1:
                    prev_period, prev_value = trend[-2]
                    line["prev_value"], line["prev_period"] = prev_value, prev_period
                    line["delta"] = value - prev_value
                    line["delta_pct"] = (round((value - prev_value) / prev_value * 100, 2)
                                         if prev_value else None)
            # Пороги подсветки работают ПОСТРОЧНО: у разрезов одного показателя
            # значения разного масштаба, общий цвет карточки был бы неверен.
            line["alert"] = evaluate_alert("kpi", cfg, {"value": value})
            lines.append(line)
        return {"type": "kpi_group", "title": name, "subject": subject or name,
                "unit": cfg.get("unit"), "lines": lines}

    if t == "matrix":
        # Матрица «строка × отчётная дата»: как КАЖДАЯ строка формы двигалась от
        # отчёта к отчёту. Такого разреза у нас не было: «Динамика» сворачивает
        # все строки в одно число, сводная таблица показывает строки × поля на
        # ОДНУ дату. Вопрос «какой район просел на прошлой неделе» до сих пор
        # требовал открывать несколько срезов подряд и сравнивать глазами.
        if not cfg.get("dataset_code") or not (cfg.get("value_field") or cfg.get("value_fields")):
            raise DashboardError("Матрица: укажите dataset_code и показатель (value_field)")
        try:
            max_periods = int(cfg.get("max_periods") or 12)
        except (TypeError, ValueError):
            max_periods = 12
        max_periods = max(2, min(max_periods, 52))
        # Два разреза одной матрицы. «По строкам» отвечает на «какой район
        # просел», «по показателям» — на «какой показатель какой был на каждую
        # дату». У сводной формы строка одна, и первый разрез вырождается в
        # одну строку; второй как раз для неё.
        by_fields = (cfg.get("by") == "fields")
        if by_fields:
            fields = [f for f in (cfg.get("value_fields") or []) if f]
            if not cfg.get("dataset_code") or not fields:
                raise DashboardError("Матрица по показателям: укажите dataset_code и показатели")
            m = await _dataset_field_period_matrix(
                conn, org_id, cfg["dataset_code"], fields,
                from_date, to_date, row, allowed, max_periods)
        else:
            m = await _dataset_row_period_matrix(
                conn, org_id, cfg["dataset_code"], cfg["value_field"],
                from_date, to_date, row, allowed, max_periods)
        periods = m["periods"]
        n = len(periods)
        matrix_rows: List[dict] = []
        matrix_totals: List[Optional[float]] = [None] * n
        for lbl in m["labels"]:
            cells = m["grid"][lbl]
            deltas: List[Optional[float]] = [None] * n
            pcts: List[Optional[float]] = [None] * n
            prev_cell: Optional[float] = None
            for i, v in enumerate(cells):
                if v is None:
                    continue
                if prev_cell is not None:
                    deltas[i] = v - prev_cell
                    # Прирост в процентах от НУЛЯ не считается: «рост на
                    # бесконечность» ничего не сообщает, честнее показать
                    # только абсолютное изменение.
                    pcts[i] = ((v - prev_cell) / prev_cell * 100.0) if prev_cell else None
                prev_cell = v
                matrix_totals[i] = (matrix_totals[i] or 0.0) + v
            last = next((v for v in reversed(cells) if v is not None), None)
            first = next((v for v in cells if v is not None), None)
            matrix_rows.append({
                "row": (m.get("names", {}).get(lbl, lbl) if by_fields else lbl),
                "field": lbl if by_fields else None,
                "aggregate": (m.get("how", {}).get(lbl) if by_fields else None),
                "values": cells, "deltas": deltas, "delta_pcts": pcts,
                "last": last,
                # Итог строки за весь показанный отрезок — то же, что «всего» у
                # «Динамики»: без него матрица отвечает на «сколько сейчас», но
                # не на «куда движется за период».
                "total_change": (last - first) if (last is not None and first is not None) else None,
                "total_change_pct": (
                    (last - first) / first * 100.0
                    if (last is not None and first is not None and first) else None),
            })
        if by_fields:
            # Итог по столбцу здесь сложил бы РАЗНЫЕ показатели (обращения с
            # процентами) — число получилось бы бессмысленным, поэтому его нет.
            subtitle = f"показателей: {len(matrix_rows)}"
        else:
            title = await _field_title(conn, org_id, cfg["dataset_code"], cfg["value_field"])
            subtitle = title or cfg["value_field"]
        return {"type": "matrix", "title": name, "by": ("fields" if by_fields else "rows"),
                # Дата, за которую данные показаны на самом деле: у матрицы это
                # её последний столбец. Общая метка свежести здесь соврала бы —
                # при фильтре периода она показывала бы дату последнего выпуска,
                # которого на экране нет.
                "as_of": (periods[-1] if periods else None),
                "periods": periods, "rows": matrix_rows,
                "col_totals": (None if by_fields else matrix_totals),
                "field_title": subtitle, "unit": cfg.get("unit"),
                "total_periods": m["total_periods"], "shown_periods": m["shown_periods"]}

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
               "change": change, "change_pct": change_pct,
               # Та же логика, что у матрицы: свежесть виджета — его последняя
               # показанная точка, а не последний выпуск набора данных.
               "as_of": (periods[-1] if periods else None)}
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
        if cfg.get("growth_index"):
            # Индекс роста: первая точка = 100 %. Отвечает не на «сколько», а на
            # «насколько выросло с начала отрезка» — единственный способ
            # сравнивать показатели разного масштаба (2,3 млн уведомлений и
            # 7 тыс. записей) на одной оси, не превращая маленький ряд в прямую
            # у нуля. Считается на сервере, а не на клиенте, чтобы выгрузка в
            # Excel показывала ровно то же, что экран.
            # База — первый отчёт ряда либо ВЫБРАННЫЙ человеком: вопрос «сколько
            # сейчас относительно 22.07» задают чаще, чем «относительно начала
            # ряда», а ряд к тому же меняется с приходом новых данных.
            want = cfg.get("index_base_period")
            idx = periods.index(want) if want in periods else None
            if want and idx is None:
                res["index_base_missing"] = want
            if idx is None:
                idx = next((i for i, v in enumerate(values) if v), None)
            base = values[idx] if idx is not None else None
            if base and idx is not None:
                res["index_values"] = [round(v / base * 100.0, 2) if v is not None else None
                                       for v in values]
                res["index_base_period"] = periods[idx]
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
        how, rows_used = "sum", 0
        if cfg.get("formula"):
            value, unit = await _formula_value(conn, org_id, cfg["formula"]), cfg.get("unit")
        elif cfg.get("metric_code"):
            value, unit = await _metric_value(conn, org_id, cfg["metric_code"])
        elif cfg.get("dataset_code") and cfg.get("value_field"):
            value, how, rows_used = await _column_value(
                conn, org_id, cfg, cfg["value_field"], row, allowed, period)
            unit = cfg.get("unit")
        else:
            raise DashboardError("KPI: укажите формулу, metric_code или dataset_code+value_field")
        res = {"type": "kpi", "value": value, "unit": unit, "title": name}
        # Способ сворачивания строк подписывается в карточке, но только когда
        # он неочевиден: среднее по нескольким строкам — приближение, и выдать
        # его за точный итог значило бы соврать. Сумма подписи не требует.
        if how == "avg" and rows_used > 1:
            res["aggregate"], res["rows_used"] = how, rows_used
        # Два необязательных украшения, которые превращают голое число в
        # показатель: прирост к прошлому отчёту и мини-график по периодам.
        # Оба ВЫКЛЮЧЕНЫ по умолчанию — это лишние запросы, а на странице
        # карточек бывает полтора десятка.
        if cfg.get("dataset_code") and cfg.get("value_field") and (cfg.get("compare_prev") or cfg.get("spark")):
            # 🔴 Ряд обрезаем ПО ЭФФЕКТИВНОМУ ПЕРИОДУ виджета, а не берём весь.
            # Иначе карточка, закреплённая за отчётом (страница-срез) или
            # суженная фильтром периода, рисовала бы линию по точкам, пришедшим
            # ПОЗЖЕ её собственной даты, — снимок показывал бы будущее, а
            # «прирост к прошлому» считался бы от последней пары ряда, а не от
            # пары, соседней с этим отчётом.
            trend = await _dataset_period_series(
                conn, org_id, cfg["dataset_code"], cfg["value_field"], None, period, row, allowed)
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
        how, rows_used = "sum", 0
        if cfg.get("formula"):
            value, unit = await _formula_value(conn, org_id, cfg["formula"]), cfg.get("unit")
        elif cfg.get("metric_code"):
            value, unit = await _metric_value(conn, org_id, cfg["metric_code"])
        elif cfg.get("dataset_code") and cfg.get("value_field"):
            value, how, rows_used = await _column_value(
                conn, org_id, cfg, cfg["value_field"], row, allowed, period)
            unit = cfg.get("unit")
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
        if how == "avg" and rows_used > 1:
            res["aggregate"], res["rows_used"] = how, rows_used
        _apply_target(res, cfg, value)
        res["alert"] = evaluate_alert("kpi", cfg, res)  # те же пороги, что и KPI
        return res

    if t == "plan_fact":
        if cfg.get("plan_metric") and cfg.get("fact_metric"):
            plan, unit = await _metric_value(conn, org_id, cfg["plan_metric"])
            fact, _ = await _metric_value(conn, org_id, cfg["fact_metric"])
        elif cfg.get("dataset_code") and cfg.get("plan_field") and cfg.get("fact_field"):
            # Тем же правилом, что и карточка: план и факт в процентах по
            # нескольким строкам складывать нельзя.
            plan, _, _ = await _column_value(conn, org_id, cfg, cfg["plan_field"], row, allowed, period)
            fact, how_fact, _ = await _column_value(conn, org_id, cfg, cfg["fact_field"], row, allowed, period)
            unit = cfg.get("unit")
        else:
            raise DashboardError("План-факт: укажите plan_metric+fact_metric или dataset_code+plan_field+fact_field")
        pct = (fact / plan * 100.0) if plan else None
        res = {"type": "plan_fact", "plan": plan, "fact": fact, "delta": fact - plan, "pct": pct, "unit": unit, "title": name}
        if cfg.get("dataset_code") and cfg.get("plan_field") and cfg.get("fact_field"):
            # «Выполнение: 656,87 %» бывает арифметически верным и при этом
            # бессмысленным: план задан на месяц, а факт идёт нарастающим итогом
            # с начала года. Считать за человека нельзя — данные такие, какие
            # они есть, — но молчать об этом хуже: цифру несут руководителю.
            res["slice_note"] = await _slice_mismatch(
                conn, org_id, cfg["dataset_code"], cfg["plan_field"], cfg["fact_field"], period)
        if cfg.get("forecast") and cfg.get("dataset_code") and cfg.get("fact_field") and how_fact == "sum":
            # «Успеем ли к сроку» — вопрос, ради которого на план-факт и смотрят;
            # до сих пор его считали в уме. Прогноз строится ТОЛЬКО для
            # суммируемых показателей: у долей и процентов «темп в день» смысла
            # не имеет, а правдоподобная с виду дата хуже её отсутствия.
            series = await _dataset_period_series(
                conn, org_id, cfg["dataset_code"], cfg["fact_field"], None, period, row, allowed)
            res["forecast"] = _plan_forecast(series, plan, fact)
        res["alert"] = evaluate_alert("plan_fact", cfg, res)
        return res

    if t == "bullet":
        # «Полосы»: несколько пар «план + факт» ОДНОЙ карточкой, строка на пару.
        # Отличие от «План-факта» — не в оформлении: тот показывает одну пару, и
        # три показателя занимали три карточки, где имя весит больше числа, а
        # сравнить их между собой нельзя вовсе (у каждого своя шкала).
        pairs = cfg.get("pairs") or []
        if not cfg.get("dataset_code") or not pairs:
            raise DashboardError("Полосы план-факт: укажите dataset_code и хотя бы одну пару «план + факт»")
        code = cfg["dataset_code"]
        # Имена граф читаем ОДНИМ запросом на весь виджет, а не по одному на
        # строку: на десяти парах это была бы пара десятков лишних обращений.
        titles = await _field_titles(conn, org_id, code, period)
        out_rows: List[dict] = []
        for pair in pairs[:BULLET_MAX_PAIRS]:
            plan_f, fact_f = pair.get("plan_field"), pair.get("fact_field")
            if not plan_f or not fact_f:
                raise DashboardError("Полосы план-факт: у каждой строки нужны и план, и факт")
            plan, _, _ = await _column_value(conn, org_id, cfg, plan_f, row, allowed, period)
            fact, _, _ = await _column_value(conn, org_id, cfg, fact_f, row, allowed, period)
            pct = (fact / plan * 100.0) if plan else None
            # Цвет — ТЕ ЖЕ пороги, что у «План-факта» и спидометра: своя шкала
            # у полос означала бы, что красный на соседних виджетах значит разное.
            alert = evaluate_alert("plan_fact", cfg, {"pct": pct, "plan": plan, "fact": fact})
            out_rows.append({
                "label": pair.get("label") or titles.get(fact_f) or fact_f,
                "plan": plan, "fact": fact, "delta": fact - plan, "pct": pct,
                "level": (alert or {}).get("level"), "color": (alert or {}).get("color"),
                # Предупреждение о несопоставимых разрезах — на КАЖДОЙ строке
                # своё: в одной карточке легко оказаться паре «план на срок +
                # накопительный факт» рядом с парой «неделя + неделя».
                "slice_note": slice_note(titles.get(plan_f), titles.get(fact_f)),
            })
        # Шкала общая на все строки, и в этом весь смысл: 100 % — это план, и
        # ровно поэтому показатели разного масштаба становятся сравнимыми.
        # Потолок не даём задрать одному перевыполнившему: при 656 % остальные
        # полосы схлопнулись бы в невидимые огрызки. Обрезанные помечаем, а
        # само число печатается всегда — из виду ничего не пропадает.
        top = max([r["pct"] for r in out_rows if r["pct"] is not None] or [0])
        scale = min(BULLET_SCALE_CAP, max(BULLET_SCALE_MIN, _nice_ceiling(top)))
        for r in out_rows:
            r["clipped"] = r["pct"] is not None and r["pct"] > scale
        return {"type": "bullet", "title": name, "rows": out_rows,
                "scale_max": scale, "unit": cfg.get("unit")}

    if t == "thermometer":
        # «Термометр к сроку»: успеваем ли к дате. Вопрос не в том, сколько
        # накоплено, — на это отвечает «План-факт», — а в том, обгоняет ли темп
        # календарь. У заказчика планы заданы именно так («до 1 сентября»), и
        # до сих пор ответ считали в уме, сопоставляя проценты с датой.
        if not (cfg.get("dataset_code") and cfg.get("plan_field") and cfg.get("fact_field")):
            raise DashboardError("Термометр: укажите dataset_code, поле плана и поле факта")
        deadline = _as_date(cfg.get("deadline"))
        if deadline is None:
            raise DashboardError("Термометр: укажите срок (дату), к которому должен быть выполнен план")
        code = cfg["dataset_code"]
        plan, _, _ = await _column_value(conn, org_id, cfg, cfg["plan_field"], row, allowed, period)
        fact, how_fact, _ = await _column_value(conn, org_id, cfg, cfg["fact_field"], row, allowed, period)
        series = await _dataset_period_series(
            conn, org_id, code, cfg["fact_field"], None, period, row, allowed)
        # Начало отсчёта: либо задано человеком, либо ПЕРВЫЙ отчёт этой формы.
        # Выдумывать «начало года» нельзя — форма могла начаться в мае, и тогда
        # «прошло 66 % срока» было бы неправдой в пользу отставания.
        start = _as_date(cfg.get("start")) or (_as_date(series[0][0]) if series else None)
        as_of = (_as_date(series[-1][0]) if series else None) or start
        done_pct = (fact / plan * 100.0) if plan else None
        res = {"type": "thermometer", "title": name, "plan": plan, "fact": fact,
               "delta": (fact - plan) if (plan is not None and fact is not None) else None,
               "pct": done_pct, "unit": cfg.get("unit"),
               "deadline": deadline.isoformat(),
               "start": start.isoformat() if start else None,
               "as_of": as_of.isoformat() if as_of else None}
        if start and as_of and deadline > start:
            total = (deadline - start).days
            gone = max(0, min(total, (as_of - start).days))
            res["days_total"], res["days_left"] = total, (deadline - as_of).days
            res["elapsed_pct"] = gone / total * 100.0
            if done_pct is not None:
                # Опережение/отставание — в ПУНКТАХ: «выполнено 62 %, прошло
                # 71 % срока» читается однозначно, а «отстаём на 13 %» — нет
                # (13 % от чего?). Тот же довод, что у прироста долей на
                # «Главной».
                res["lead_pp"] = done_pct - res["elapsed_pct"]
            # «Сколько нужно в день, чтобы успеть» — то, ради чего на срок и
            # смотрят. Рядом с фактическим темпом из прогноза это прямой ответ
            # «хватает ли нынешней скорости», а не повод считать в уме.
            if plan is not None and fact is not None and res["days_left"] > 0 and fact < plan:
                res["need_per_day"] = (plan - fact) / res["days_left"]
        # Прогноз — ТОТ ЖЕ, что у «План-факта»: второй расчёт «когда успеем»
        # рядом с первым однажды дал бы две разные даты на одном экране.
        if how_fact == "sum":
            res["forecast"] = _plan_forecast(series, plan, fact)
        res["slice_note"] = await _slice_mismatch(
            conn, org_id, code, cfg["plan_field"], cfg["fact_field"], period)
        res["alert"] = evaluate_alert("plan_fact", cfg, res)
        return res

    if t == "table":
        if not cfg.get("dataset_code"):
            raise DashboardError("Таблица: укажите dataset_code")
        table = await _dataset_table(conn, org_id, cfg["dataset_code"], row, allowed, period)
        res = {"type": "table", "title": name, **table}
        # Условное форматирование ячеек: цвет по порогам считаем ТЕМ ЖЕ кодом,
        # что красит карточку показателя, а «полоску по величине» отдаём
        # клиенту — в ней нет правила, только соотношение уже пришедших чисел.
        fmt = cfg.get("cell_format") or {}
        if fmt:
            res["cell_format"] = fmt
            cell_alert_levels(cfg, res.get("rows") or [])
            if any(m == "alert" for m in fmt.values()):
                res["alert_styles"] = alert_styles()
        return res

    # bar | line | pie
    if not cfg.get("dataset_code") or not cfg.get("value_field"):
        raise DashboardError("График: укажите dataset_code и value_field")
    series = await _dataset_series(conn, org_id, cfg["dataset_code"], cfg["value_field"], row, allowed, period)
    res = {"type": t, "title": name,
           "categories": [s["category"] for s in series],
           "values": [s["value"] for s in series]}
    # Круговой диаграмме призрак не положен: две доли одна за другой не
    # накладываются и сравнить их нельзя — вышла бы каша вместо ответа.
    if t != "pie":
        await _add_ghost(conn, org_id, cfg, res, row, allowed, period)
    return res
