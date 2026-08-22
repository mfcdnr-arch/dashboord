"""Оркестрация данных виджета (вынесено из service.py, далее разбито на слои).

Публичные точки входа: compute_widget_data/compute_page_data (кэш+RLS+алерты),
preview_widget (конструктор, без сохранения), list_org_alerts (сработавшие
KPI-алерты для «Главной»), widget_drill (прозрачность показателя, drill).
Расчёт по типу виджета — в _widgetcalc, чтение датасетов/метрик — в
_widgetsources, экспорт в xlsx — в _widgetexport. Слой данных: зависит от
_alerts/_base/_rls/_rowrls и метрик.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ... import cache
from ..metrics.parser import FormulaError, extract_dependencies, parse
from ._alerts import _cfg
from ._base import WIDGET_TYPES, DashboardError
from ._rls import _can_view, visible_dashboard_ids, visible_widget_ids
from ._rowrls import allowed_rows_for_dataset, rls_tag
from ._widgetcalc import _compute_widget
from ._widgetsources import _attach_as_of, _best_metric_version, _dataset_table, _page_org, _widget_org


async def compute_widget_data(conn, org_id, widget_id: str, from_date=None, to_date=None, row=None,
                              user: Optional[dict] = None, skip_acl: bool = False) -> dict:
    w = await _widget_org(conn, org_id, widget_id)
    if w is None:
        raise DashboardError("Виджет не найден")
    # RLS: обход разрешён только явным skip_acl (внутренние агрегаты, где
    # видимость уже проверена выше). По HTTP всегда приходит user — fail closed.
    if not skip_acl and (user is None or not await _can_view(conn, org_id, user, str(w["dashboard_id"]))):
        raise DashboardError("Виджет не найден")
    # RLS widget-level: если для дашборда включён whitelist — виджет вне списка
    # для зрителя-по-гранту невидим (fail closed). Пропускаем при skip_acl
    # (батч-выдача уже отфильтровала виджеты по whitelist выше).
    if not skip_acl:
        assert user is not None  # гарантировано проверкой выше (fail closed)
        allowed = await visible_widget_ids(conn, org_id, user, str(w["dashboard_id"]))
        if allowed is not None and widget_id not in allowed:
            raise DashboardError("Виджет не найден")
    # TTL-кэш: данные виджета одинаковы для всех с ОДИНАКОВОЙ видимостью строк.
    # Ключ учитывает фильтры страницы и row-level RLS (метка по подразделению),
    # иначе отфильтрованные данные одного отдела попали бы другому. Мягкая
    # деградация при недоступном Redis.
    tag = await rls_tag(conn, user)
    key = f"wd:{widget_id}:{from_date or ''}:{to_date or ''}:{row or ''}:{tag}"
    cached = await cache.get(key)
    if cached is not None:
        try:
            return json.loads(cached)
        except ValueError:
            pass
    result = await _compute_widget(conn, org_id, w["widget_type"], w["name"], _cfg(w), from_date, to_date, row, user=user)
    # Свежесть данных: дата активного выпуска датасета («данные на X»).
    await _attach_as_of(conn, org_id, _cfg(w), result)
    try:
        await cache.set(key, json.dumps(result, ensure_ascii=False), cache.WIDGET_DATA_TTL)
    except (TypeError, ValueError):
        pass  # несериализуемый результат не кэшируем
    return result


async def compute_page_data(conn, org_id, page_id: str, user: dict,
                            from_date=None, to_date=None, row=None) -> dict:
    """Данные ВСЕХ виджетов страницы одним запросом (перф: 1 запрос вместо N).
    Доступ проверяется один раз на уровне страницы; далее компьютим виджеты
    (с кэшем/алертами). Ошибка одного виджета не рушит остальные."""
    p = await _page_org(conn, org_id, page_id)
    if p is None:
        raise DashboardError("Страница не найдена")
    if not await _can_view(conn, org_id, user, str(p["dashboard_id"])):
        raise DashboardError("Страница не найдена")
    allowed = await visible_widget_ids(conn, org_id, user, str(p["dashboard_id"]))
    rows = await conn.fetch(
        "select id from widgets where page_id=$1::uuid order by position_y, position_x", page_id)
    out = []
    for w in rows:
        wid = str(w["id"])
        if allowed is not None and wid not in allowed:
            continue  # виджет вне whitelist — не отдаём данные
        try:
            # user передаём для row-level RLS (skip_acl только пропускает повторную
            # проверку видимости дашборда/виджета — она уже сделана выше).
            data = await compute_widget_data(conn, org_id, wid, from_date, to_date, row,
                                             user=user, skip_acl=True)
            out.append({"id": wid, "data": data})
        except DashboardError as e:
            out.append({"id": wid, "error": str(e)})
    return {"page_id": page_id, "widgets": out}


async def preview_widget(conn, org_id, widget_type: str, name: Optional[str], config: dict) -> dict:
    """Предпросмотр виджета по конфигу без сохранения (для конструктора)."""
    if widget_type not in WIDGET_TYPES:
        raise DashboardError(f"Неизвестный тип виджета: {widget_type}")
    result = await _compute_widget(conn, org_id, widget_type, name or "Предпросмотр", config or {})
    return await _attach_as_of(conn, org_id, config or {}, result)


async def list_org_alerts(conn, org_id, user: dict, limit: int = 30) -> List[dict]:
    """Сработавшие KPI-алерты по доступным пользователю дашбордам — для «Главной».
    Возвращаются только уровни warn/danger (good — позитивная подсветка, не тревога)."""
    visible = await visible_dashboard_ids(conn, org_id, user)
    if not visible:
        return []
    rows = await conn.fetch(
        "select w.id, w.name, w.widget_type, w.dashboard_id, "
        "d.name as dashboard_name, d.publication_status, "
        "(select p.name from dashboard_pages p where p.id=w.page_id) as page_name "
        "from widgets w join dashboards d on d.id=w.dashboard_id "
        "where w.organization_id=$1 and w.dashboard_id = any($2::uuid[]) "
        "and (w.config ->> 'alerts') is not null "
        "order by d.name", org_id, list(visible),
    )
    out: List[dict] = []
    for w in rows:
        try:
            data = await compute_widget_data(conn, org_id, str(w["id"]), skip_acl=True)
        except DashboardError:
            continue
        al = data.get("alert")
        if not al or al["level"] not in ("warn", "danger"):
            continue
        out.append({
            "widget_id": str(w["id"]), "widget_name": w["name"], "widget_type": w["widget_type"],
            "dashboard_id": str(w["dashboard_id"]), "dashboard_name": w["dashboard_name"],
            "page_name": w["page_name"], "published": w["publication_status"] == "published",
            "level": al["level"], "label": al["label"], "measure": al["measure"], "unit": data.get("unit"),
        })
    out.sort(key=lambda x: (0 if x["level"] == "danger" else 1, x["dashboard_name"]))
    return out[:limit]


async def widget_drill(conn, org_id, widget_id: str, user: dict) -> dict:
    """Прозрачность показателя: из чего собран виджет — формулы метрик (уровень 1)
    и первичные строки датасетов (уровень 2)."""
    w = await _widget_org(conn, org_id, widget_id)
    if w is None:
        raise DashboardError("Виджет не найден")
    if not await _can_view(conn, org_id, user, str(w["dashboard_id"])):
        raise DashboardError("Виджет не найден")
    allowed = await visible_widget_ids(conn, org_id, user, str(w["dashboard_id"]))
    if allowed is not None and widget_id not in allowed:
        raise DashboardError("Виджет не найден")
    cfg = _cfg(w)
    metric_codes = [cfg[k] for k in ("metric_code", "plan_metric", "fact_metric") if cfg.get(k)]
    dataset_codes = [cfg["dataset_code"]] if cfg.get("dataset_code") else []

    metrics_info: List[dict] = []

    # Собственная формула виджета (KPI с config.formula) — показать как показатель уровня 1
    if cfg.get("formula"):
        try:
            deps = extract_dependencies(parse(cfg["formula"]))
        except FormulaError:
            deps = {"datasets": [], "metrics": []}
        metrics_info.append({
            "code": "(формула виджета)", "name": w["name"], "formula": cfg["formula"],
            "status": "widget", "version_no": None, "datasets": deps["datasets"],
        })
        dataset_codes += deps["datasets"]
        metric_codes += deps.get("metrics", [])

    for code in metric_codes:
        row = await _best_metric_version(conn, org_id, code)
        if row is None:
            continue
        ast = row["formula_ast"]
        if isinstance(ast, str):
            ast = json.loads(ast)
        deps = extract_dependencies(ast)
        metrics_info.append({
            "code": code, "name": row["name"], "formula": row["formula_expression"],
            "status": row["status"], "version_no": row["version_no"], "datasets": deps["datasets"],
            "info_text": row["info_text"], "description": row["description"],
        })
        dataset_codes += deps["datasets"]

    seen: List[str] = []
    for dc in dataset_codes:
        if dc not in seen:
            seen.append(dc)
    tables: Dict[str, Any] = {}
    for dc in seen:
        try:
            # Drill-до-первичных-строк тоже под row-level RLS.
            dc_allowed = await allowed_rows_for_dataset(conn, org_id, user, dc)
            tables[dc] = await _dataset_table(conn, org_id, dc, allowed=dc_allowed)
        except DashboardError:
            tables[dc] = {"columns": [], "rows": []}

    return {"widget": w["name"], "widget_type": w["widget_type"],
            "metrics": metrics_info, "datasets": seen, "tables": tables}


async def page_report_dates(conn, org_id, page_id: str, user: dict) -> dict:
    """Отчётные даты, доступные на этой странице, — для выбора отчёта фильтром.

    Фильтр периода умеет открыть любой прошлый отчёт (он сводит диапазон к
    последнему отчёту внутри него), но до сих пор дату приходилось набирать в
    двух календарях. При недельной форме за год это 52 даты, которые надо
    помнить. Здесь они просто перечислены.

    Даты собираются по датасетам ВИДЖЕТОВ страницы: список должен совпадать с
    тем, что страница реально способна показать.
    """
    from . import service

    wl = await service.list_page_widgets(conn, org_id, page_id, user)
    codes = sorted({str((w.get("config") or {}).get("dataset_code"))
                    for w in wl["widgets"] if (w.get("config") or {}).get("dataset_code")})
    if not codes:
        return {"dates": []}
    rows = await conn.fetch(
        "select distinct reporting_period_start as p from dataset_releases "
        "where organization_id=$1 and code = any($2::text[]) and status<>'superseded' "
        "and reporting_period_start is not null order by 1 desc limit 200", org_id, codes)
    return {"dates": [r["p"].isoformat() for r in rows]}
