"""Низкоуровневое чтение данных для виджетов (вынесено из _widgetdata.py).

Метрики (лучшая версия/значение), формулы виджета, серии/таблицы датасета
(активный выпуск / по периодам / несколько полей), свежесть выпуска. Никакой
диспетчеризации по типу виджета — только чтение из БД. Используется
_widgetcalc (расчёт по типу) и _widgetdata (оркестрация/кэш/RLS).
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from ..metrics import resolver as mr
from ..metrics.parser import FormulaError, parse
from ._base import DashboardError


async def _widget_org(conn, org_id, widget_id: str):
    return await conn.fetchrow(
        "select w.* from widgets w where w.id=$1::uuid and w.organization_id=$2", widget_id, org_id)


async def _page_org(conn, org_id, page_id: str):
    return await conn.fetchrow(
        "select p.id, p.dashboard_id from dashboard_pages p join dashboards d on d.id=p.dashboard_id "
        "where p.id=$1::uuid and d.organization_id=$2", page_id, org_id)


async def _best_metric_version(conn, org_id, code: str):
    # приоритет версии: одобренная → проверенная → любая (черновик не берётся вперёд проверенной)
    return await conn.fetchrow(
        "select m.name, m.info_text, m.description, mv.formula_expression, mv.formula_ast, mv.unit, mv.version_no, mv.status "
        "from metrics m join metric_versions mv on mv.metric_id=m.id "
        "where m.organization_id=$1 and m.code=$2 "
        "order by (case mv.status when 'approved' then 0 when 'validated' then 1 else 2 end), "
        "mv.version_no desc limit 1",
        org_id, code,
    )


async def _formula_value(conn, org_id, formula: str):
    """Вычисление произвольной формулы виджета (без сохранённой метрики)."""
    try:
        ast = parse(formula)
        return await mr.evaluate_ast(conn, org_id, ast)
    except FormulaError as e:
        raise DashboardError(str(e))


async def _metric_value(conn, org_id, code: str):
    row = await _best_metric_version(conn, org_id, code)
    if row is None:
        # Различаем «метрики нет» и «метрика есть, но формулы у неё нет»:
        # заказчик завёл метрику, не сохранил версию формулы и получил
        # «не найдена» — сообщение уводило искать опечатку в коде.
        exists = await conn.fetchval(
            "select 1 from metrics where organization_id=$1 and code=$2", org_id, code)
        if exists:
            raise DashboardError(
                f"У метрики '{code}' нет ни одной версии формулы. "
                "Откройте её в разделе «Метрики» и сохраните формулу."
            )
        raise DashboardError(f"Метрика '{code}' не найдена")
    ast = row["formula_ast"]
    if isinstance(ast, str):
        ast = json.loads(ast)
    try:
        value = await mr.evaluate_ast(conn, org_id, ast)
    except FormulaError as e:
        raise DashboardError(str(e))
    return value, row["unit"]


def _row_acl_clause(params: list, allowed) -> str:
    """Добавляет фильтр по разрешённым строкам (row-level RLS) к запросу
    dataset_values. allowed=None — без фильтра; set — whitelist row_label
    (пустой набор → ни одной строки)."""
    if allowed is None:
        return ""
    params.append(list(allowed))
    return f" and row_label = any(${len(params)}::text[])"


async def _dataset_series(conn, org_id, dataset_code: str, value_field: str, row=None, allowed=None,
                          period=None):
    """`period` — брать выпуск ЗА ЭТУ отчётную дату, а не последний.

    Нужен страницам «по неделям»: такая страница показывает данные конкретной
    недели и не должна меняться, когда придёт следующая. Пусто — обычное
    поведение: последний неотменённый выпуск, то есть свежие цифры.
    """
    rel = await mr._active_release(conn, org_id, dataset_code, period)
    if rel is None:
        raise DashboardError(f"Датасет '{dataset_code}' не найден или не выпущен")
    params: list = [rel, value_field, row]
    acl = _row_acl_clause(params, allowed)
    rows = await conn.fetch(
        "select row_label, value_number from dataset_values "
        "where dataset_release_id=$1 and canonical_field_code=$2 and value_number is not null "
        f"and ($3::text is null or row_label=$3){acl} order by row_index", *params,
    )
    return [{"category": r["row_label"], "value": float(r["value_number"])} for r in rows]


async def _field_title(conn, org_id, dataset_code: str, field_code: str, period=None) -> Optional[str]:
    """Человеческое имя столбца («… · Доля, %»): по нему видно, можно ли его
    складывать. Код поля для этого не годится — он транслит и обрезан."""
    rel = await mr._active_release(conn, org_id, dataset_code, period)
    if rel is None:
        return None
    return await conn.fetchval(
        "select cf.name from canonical_fields cf "
        "where cf.code=$2 and cf.object_id=(select object_id from dataset_releases where id=$1)",
        rel, field_code)


async def _dataset_multi_series(conn, org_id, dataset_code: str, value_fields: List[str], row=None,
                                allowed=None, period=None) -> dict:
    """Несколько серий по одному датасету: категории=строки, серия=каждое поле."""
    rel = await mr._active_release(conn, org_id, dataset_code, period)
    if rel is None:
        raise DashboardError(f"Датасет '{dataset_code}' не найден или не выпущен")
    names = {r["code"]: r["name"] for r in await conn.fetch(
        "select drf.canonical_field_code as code, coalesce(cf.name, drf.canonical_field_code) as name "
        "from dataset_release_fields drf "
        "left join canonical_fields cf on cf.code=drf.canonical_field_code "
        "  and cf.object_id=(select object_id from dataset_releases where id=$1) "
        "where drf.dataset_release_id=$1", rel)}
    params: list = [rel, value_fields, row]
    acl = _row_acl_clause(params, allowed)
    rows = await conn.fetch(
        "select row_index, row_label, canonical_field_code, value_number from dataset_values "
        "where dataset_release_id=$1 and canonical_field_code = any($2::text[]) and value_number is not null "
        f"and ($3::text is null or row_label=$3){acl} order by row_index", *params)
    categories: List[str] = []
    per: Dict[str, Dict[str, float]] = {f: {} for f in value_fields}
    for r in rows:
        lbl = r["row_label"]
        if lbl not in categories:
            categories.append(lbl)
        per[r["canonical_field_code"]][lbl] = float(r["value_number"])
    series = [{"name": names.get(f, f), "data": [per[f].get(cat) for cat in categories]} for f in value_fields]
    return {"categories": categories, "series": series}


async def _dataset_period_series(conn, org_id, dataset_code: str, value_field: str,
                                from_date=None, to_date=None, row=None, allowed=None):
    """Ряд по периодам: для каждого активного выпуска датасета — сумма поля (динамика)."""
    rels = await conn.fetch(
        "select id, reporting_period_start from dataset_releases "
        "where organization_id=$1 and code=$2 and status <> 'superseded' "
        "and ($3::text is null or reporting_period_start >= $3::text::date) "
        "and ($4::text is null or reporting_period_start <= $4::text::date) "
        "order by reporting_period_start nulls last",
        org_id, dataset_code, from_date, to_date,
    )
    if not rels:
        raise DashboardError(f"Датасет '{dataset_code}' не найден или не выпущен")
    out = []
    for r in rels:
        params: list = [r["id"], value_field, row]
        acl = _row_acl_clause(params, allowed)
        s = await conn.fetchval(
            "select coalesce(sum(value_number),0) from dataset_values "
            f"where dataset_release_id=$1 and canonical_field_code=$2 and ($3::text is null or row_label=$3){acl}",
            *params)
        period = r["reporting_period_start"].isoformat() if r["reporting_period_start"] else "—"
        out.append((period, float(s)))
    return out


async def _dataset_table(conn, org_id, dataset_code: str, row=None, allowed=None, period=None):
    rel = await mr._active_release(conn, org_id, dataset_code, period)
    if rel is None:
        raise DashboardError(f"Датасет '{dataset_code}' не найден или не выпущен")
    fields = await conn.fetch(
        "select distinct canonical_field_code from dataset_values where dataset_release_id=$1 "
        "order by canonical_field_code", rel)
    cols = [f["canonical_field_code"] for f in fields]
    params: list = [rel, row]
    acl = _row_acl_clause(params, allowed)
    vals = await conn.fetch(
        "select row_index, row_label, canonical_field_code, value_text, value_number "
        f"from dataset_values where dataset_release_id=$1 and ($2::text is null or row_label=$2){acl} "
        "order by row_index", *params)
    by_row: Dict[int, dict] = {}
    for v in vals:
        r = by_row.setdefault(v["row_index"], {"__row__": v["row_label"]})
        r[v["canonical_field_code"]] = (
            float(v["value_number"]) if v["value_number"] is not None else v["value_text"])
    rows = [{"row": by_row[i].get("__row__"), **{c: by_row[i].get(c) for c in cols}}
            for i in sorted(by_row)]
    # Человеческие названия столбцов: в таблице на дашборде руководитель должен
    # видеть «Количество обращений … за отчётную неделю», а не машинный код
    # поля. Ключ остаётся кодом — по нему собраны строки и работает экспорт.
    titles = await conn.fetch(
        "select cf.code, cf.name from canonical_fields cf "
        "join dataset_releases r on r.object_id = cf.object_id "
        "where r.id=$1 and cf.code = any($2::text[])",
        rel, cols,
    )
    names = {t["code"]: t["name"] for t in titles}
    return {"columns": cols, "column_titles": names, "rows": rows}


async def _dataset_as_of(conn, org_id, dataset_code: str, period=None):
    """Дата выпуска, по которому посчитан виджет, — для метки свежести.

    У виджета с закреплённым периодом это сам период: иначе страница «за
    05.08» подписывалась бы датой последнего выпуска и вводила в заблуждение.
    """
    if period:
        return str(period)
    d = await conn.fetchval(
        "select reporting_period_start from dataset_releases "
        "where organization_id=$1 and code=$2 and status<>'superseded' "
        "order by reporting_period_start desc nulls last, created_at desc limit 1",
        org_id, dataset_code)
    return d.isoformat() if d else None


async def _attach_as_of(conn, org_id, cfg: dict, result):
    """Добавляет метку свежести as_of (дата активного выпуска) для датасетных
    виджетов. Именованные метрики/объектные — без метки (объективны)."""
    ds = (cfg or {}).get("dataset_code")
    if ds and isinstance(result, dict) and "as_of" not in result:
        result["as_of"] = await _dataset_as_of(conn, org_id, ds, (cfg or {}).get("period"))
        if (cfg or {}).get("period"):
            # Страница «по неделям» показывает срез и не обновляется — об этом
            # надо сказать, иначе её примут за устаревший дашборд.
            result["period_locked"] = True
    return result


async def _dataset_row_period_matrix(conn, org_id, dataset_code: str, value_field: str,
                                     from_date=None, to_date=None, row=None, allowed=None,
                                     max_periods: int = 12):
    """Матрица «строка × отчётная дата» по одному показателю.

    Ни один существующий источник этого не даёт: `_dataset_period_series`
    сворачивает все строки в одно число за период, а `_dataset_multi_series` —
    это строки × ПОЛЯ на ОДНУ дату. Здесь нужен третий разрез: как каждая
    строка формы (район, отделение) двигалась от отчёта к отчёту.

    `max_periods` — сколько последних отчётов показать. Ограничение
    содержательное, а не техническое: недельная форма за год даёт 52 столбца,
    и матрица перестаёт читаться; сколько отчётов есть на самом деле,
    возвращается отдельно (`total_periods`), чтобы это можно было сказать
    человеку, а не умолчать.
    """
    rels = await conn.fetch(
        "select id, reporting_period_start from dataset_releases "
        "where organization_id=$1 and code=$2 and status <> 'superseded' "
        "and ($3::text is null or reporting_period_start >= $3::text::date) "
        "and ($4::text is null or reporting_period_start <= $4::text::date) "
        "order by reporting_period_start nulls last",
        org_id, dataset_code, from_date, to_date,
    )
    if not rels:
        raise DashboardError(f"Датасет '{dataset_code}' не найден или не выпущен")
    total = len(rels)
    kept = rels[-max_periods:] if max_periods and total > max_periods else list(rels)
    ids = [r["id"] for r in kept]
    periods = [r["reporting_period_start"].isoformat() if r["reporting_period_start"] else "—"
               for r in kept]

    params: list = [ids, value_field, row]
    acl = _row_acl_clause(params, allowed)
    vals = await conn.fetch(
        "select dataset_release_id as rel, row_label, min(row_index) as ri, "
        "       sum(value_number) as val "
        "from dataset_values "
        "where dataset_release_id = any($1::uuid[]) and canonical_field_code=$2 "
        f"and value_number is not null and ($3::text is null or row_label=$3){acl} "
        "group by dataset_release_id, row_label", *params)

    pos = {rid: i for i, rid in enumerate(ids)}
    # Порядок строк — как в САМОМ СВЕЖЕМ отчёте (там актуальный состав районов),
    # строки, которых в нём уже нет, идут следом: молча терять их нельзя, по ним
    # есть история.
    order: Dict[str, tuple] = {}
    grid: Dict[str, List[Optional[float]]] = {}
    for v in vals:
        lbl = v["row_label"]
        cells = grid.setdefault(lbl, [None] * len(ids))
        cells[pos[v["rel"]]] = float(v["val"])
        key = (-pos[v["rel"]], int(v["ri"] or 0))
        if lbl not in order or key < order[lbl]:
            order[lbl] = key
    labels = sorted(grid, key=lambda x: order[x])
    return {"periods": periods, "labels": labels, "grid": grid,
            "total_periods": total, "shown_periods": len(ids)}
