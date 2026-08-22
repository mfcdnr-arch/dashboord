"""Место выбранной строки среди остальных — содержимое drill-down по строкам.

Когда человек проваливается в строку данных (клик по строке таблицы или по
столбцу графика), страница показывает её цифры. Но сама по себе цифра не
отвечает на вопрос, ради которого в строку и проваливаются: «это много или
мало на фоне других?». Здесь считается ответ: какое место строка занимает по
главным показателям страницы, какую долю от общего итога даёт и кто впереди.

Показатели берутся НЕ из головы, а из самой страницы: датасет и поля — те,
которые чаще всего используют её виджеты. Иначе разбор говорил бы об одном, а
страница показывала другое.
"""
from typing import Optional

from ._base import DashboardError
from ._rowrls import allowed_rows_for_dataset
from ._widgetcalc import _period_for_range
from ._widgetsources import _dataset_multi_series

# Больше трёх показателей в одну строку разбора не помещается, а читать их
# всё равно перестают: место по главному показателю отвечает на вопрос.
MAX_METRICS = 3
# Поля, из которых виджет берёт число (см. _widgetcalc): собираем их все.
FIELD_KEYS = ("value_field", "fact_field", "plan_field")


def _collect(widgets: list) -> tuple[Optional[str], list, Optional[str]]:
    """Главный датасет страницы, его самые ходовые поля и закреплённый период."""
    ds_hits: dict = {}
    field_hits: dict = {}
    periods = set()
    for w in widgets:
        cfg = w.get("config") or {}
        code = cfg.get("dataset_code")
        if not code:
            continue
        ds_hits[code] = ds_hits.get(code, 0) + 1
        periods.add(cfg.get("period"))
        for key in FIELD_KEYS:
            f = cfg.get(key)
            if isinstance(f, str) and f:
                field_hits.setdefault(code, {})
                field_hits[code][f] = field_hits[code].get(f, 0) + 1
        for f in cfg.get("value_fields") or []:
            if isinstance(f, str) and f:
                field_hits.setdefault(code, {})
                field_hits[code][f] = field_hits[code].get(f, 0) + 1
    if not ds_hits:
        return None, [], None
    code = max(ds_hits, key=lambda c: ds_hits[c])
    hits = field_hits.get(code, {})
    fields = sorted(hits, key=lambda f: (-hits[f], f))[:MAX_METRICS]
    # Период страницы-среза: он одинаков у всех её виджетов. Если периоды
    # разные (обычная сводная страница), закреплять нечего.
    period = periods.pop() if len(periods) == 1 else None
    return code, fields, period


async def page_row_rank(conn, org_id, page_id: str, row: str, user: dict,
                        from_date=None, to_date=None) -> dict:
    from . import service  # ленивый импорт: service тянет этот модуль

    if not (row or "").strip():
        raise DashboardError("Не указана строка")
    wl = await service.list_page_widgets(conn, org_id, page_id, user)
    code, fields, period = _collect(wl["widgets"])
    if not code or not fields:
        # Страница без датасетных виджетов (только метрики/текст) — сравнивать
        # нечего, и это не ошибка: отвечаем честно пустым разбором.
        return {"row": row, "dataset_code": None, "metrics": [], "rows_total": 0}

    if period is None:
        period = await _period_for_range(conn, org_id, code, from_date, to_date)
    allowed = await allowed_rows_for_dataset(conn, org_id, user, code) if user is not None else None

    ms = await _dataset_multi_series(conn, org_id, code, fields, None, allowed, period)
    cats: list = ms.get("categories") or []
    metrics = []
    # Серии идут в том же порядке, что и запрошенные поля (см.
    # _dataset_multi_series) — по индексу, чтобы у показателя были и код, и имя.
    series = ms.get("series") or []
    for i, field in enumerate(fields):
        if i >= len(series):
            break
        s = series[i]
        data = [v if isinstance(v, (int, float)) else None for v in (s.get("data") or [])]
        pairs = [(cats[i], v) for i, v in enumerate(data) if i < len(cats) and v is not None]
        if not pairs:
            continue
        total = sum(v for _, v in pairs)
        ordered = sorted(pairs, key=lambda p: -p[1])
        rank = next((i + 1 for i, (name, _) in enumerate(ordered) if name == row), None)
        if rank is None:
            continue
        value = dict(pairs)[row]
        leader = ordered[0]
        metrics.append({
            "field": field,
            "name": s.get("name"),
            "value": value,
            "rank": rank,
            "rows": len(ordered),
            "share": (value / total * 100) if total else None,
            "total": total,
            # Лидер нужен, чтобы «3-е место» было с чем сравнить: без верхней
            # планки место — просто число.
            "leader": leader[0],
            "leader_value": leader[1],
        })
    return {"row": row, "dataset_code": code, "period": period,
            "rows_total": len(cats), "metrics": metrics}
