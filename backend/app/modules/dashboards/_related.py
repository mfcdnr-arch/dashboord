"""Куда можно перейти ОТ ЭТОЙ ЦИФРЫ (п. 1 списка заказчика, прототип).

Дашборд отвечает «сколько», но следующий вопрос руководителя всегда один и тот
же: «а почему столько?» Сегодня ответ приходится искать руками — открыть другой
дашборд, вспомнить, в какой форме лежит показатель, найти соседние графы.

Здесь система отвечает на это сама, разбирая то, что уже знает о виджете:

  • **из чего складывается** — формула показателя и первичные строки (это уже
    существующий разбор «🔍 подробнее», сюда он попадает как пункт меню);
  • **где ещё есть этот показатель** — другие виджеты, которые смотрят на тот
    же `metric_code` или ту же графу формы; отвечает на «а в другом отчёте
    цифра такая же?»;
  • **соседи по форме** — остальные графы того же набора данных: обращения,
    отправленные, доставленные лежат рядом, и смотреть их порознь бессмысленно;
  • **смотреть в динамике** — есть ли по этому показателю несколько отчётных
    периодов, то есть можно ли вообще построить движение.

**Связки НЕ настраиваются вручную.** Заказчику это предлагалось, и от этого
отказались сознательно: настроенная руками связь устаревает молча — форма
меняется, показатель переименовывают, а меню продолжает вести в никуда. Всё
здесь выводится из текущих данных, поэтому не может разойтись с ними.

**Видимость соблюдается:** «где ещё есть» строится только по дашбордам, которые
доступны ЭТОМУ человеку (`visible_dashboard_ids`). Иначе меню превратилось бы в
оглашение чужих отчётов: даже одни названия говорят, какие показатели за кем
закреплены.
"""
from __future__ import annotations

from typing import Optional

from ._base import DashboardError
from ._rls import visible_dashboard_ids

# Сколько пунктов показываем в каждой группе. Меню — это подсказка «куда
# дальше», а не поиск: длинный список читают хуже, чем короткий.
MAX_ITEMS = 8


async def widget_related(conn, org_id, user: dict, widget_id: str) -> dict:
    w = await conn.fetchrow(
        "select w.id, w.name, w.widget_type, w.config, w.dashboard_id, w.page_id "
        "from widgets w where w.id=$1::uuid and w.organization_id=$2", widget_id, org_id)
    if w is None:
        raise DashboardError("Виджет не найден")
    visible = await visible_dashboard_ids(conn, org_id, user)
    if str(w["dashboard_id"]) not in visible:
        raise DashboardError("Виджет не найден")

    cfg = w["config"] or {}
    if isinstance(cfg, str):
        import json
        cfg = json.loads(cfg)
    metric_code: Optional[str] = cfg.get("metric_code")
    dataset_code: Optional[str] = cfg.get("dataset_code")
    value_field: Optional[str] = cfg.get("value_field")

    subject = await _subject(conn, org_id, metric_code, dataset_code, value_field)
    return {
        "widget_id": str(w["id"]),
        "widget_name": w["name"],
        "subject": subject,
        "elsewhere": await _elsewhere(conn, org_id, visible, widget_id, metric_code,
                                      dataset_code, value_field),
        "siblings": await _siblings(conn, org_id, dataset_code, value_field, w["dashboard_id"]),
        "dynamics": await _dynamics(conn, org_id, dataset_code),
        # Куда класть новую карточку, если человек решит завести соседа:
        # на ТУ ЖЕ страницу, с которой он смотрит.
        "page_id": str(w["page_id"]) if w["page_id"] else None,
        "dashboard_id": str(w["dashboard_id"]),
    }


async def _subject(conn, org_id, metric_code, dataset_code, value_field) -> dict:
    """Про что эта цифра — показатель или графа формы."""
    if metric_code:
        row = await conn.fetchrow(
            "select name from metrics where organization_id=$1 and code=$2", org_id, metric_code)
        return {"kind": "metric", "code": metric_code,
                "name": row["name"] if row else metric_code}
    if dataset_code and value_field:
        row = await conn.fetchrow(
            "select cf.name from canonical_fields cf join dataset_releases r on r.object_id=cf.object_id "
            "where r.organization_id=$1 and r.code=$2 and cf.code=$3 limit 1",
            org_id, dataset_code, value_field)
        return {"kind": "field", "code": value_field, "dataset_code": dataset_code,
                "name": row["name"] if row else value_field}
    return {"kind": "unknown", "code": None, "name": None}


async def _elsewhere(conn, org_id, visible: set, widget_id, metric_code,
                     dataset_code, value_field) -> list:
    """Где ещё показана эта же величина — по доступным человеку дашбордам."""
    if not visible or not (metric_code or (dataset_code and value_field)):
        return []
    rows = await conn.fetch(
        "select w.id, w.name, w.widget_type, w.page_id, d.id as dashboard_id, d.name as dashboard_name, "
        "p.name as page_name "
        "from widgets w join dashboards d on d.id=w.dashboard_id "
        "left join dashboard_pages p on p.id=w.page_id "
        "where w.organization_id=$1 and w.id <> $2::uuid and d.id = any($3::uuid[]) and ("
        "  ($4::text is not null and w.config->>'metric_code' = $4) or "
        "  ($5::text is not null and $6::text is not null "
        "   and w.config->>'dataset_code' = $5 and ("
        "     w.config->>'value_field' = $6 "
        "     or w.config->'value_fields' ? $6 "
        "     or w.config->>'plan_field' = $6 or w.config->>'fact_field' = $6)))"
        "order by d.name, p.position limit $7",
        org_id, widget_id, list(visible), metric_code, dataset_code, value_field, MAX_ITEMS)
    return [{"widget_id": str(r["id"]), "widget_name": r["name"], "widget_type": r["widget_type"],
             "dashboard_id": str(r["dashboard_id"]), "dashboard_name": r["dashboard_name"],
             "page_id": str(r["page_id"]) if r["page_id"] else None,
             "page_name": r["page_name"]} for r in rows]


async def _siblings(conn, org_id, dataset_code, value_field, dashboard_id) -> list:
    """Другие графы той же формы: их смотрят вместе, а не порознь.

    У каждой сказано, ПОКАЗАНА ли она уже на этом дашборде. Разница
    существенная: если виджет есть — надо к нему перейти, если нет — завести.
    Одинаковая кнопка в обоих случаях плодила бы вторую карточку того же
    показателя рядом с первой.
    """
    if not dataset_code:
        return []
    rows = await conn.fetch(
        "select distinct cf.code, cf.name from canonical_fields cf "
        "join dataset_releases r on r.object_id=cf.object_id "
        "where r.organization_id=$1 and r.code=$2 and cf.code <> coalesce($3::text,'') "
        "  and exists (select 1 from dataset_values v join dataset_releases r2 on r2.id=v.dataset_release_id "
        "              where r2.code=r.code and v.canonical_field_code=cf.code and v.value_number is not null) "
        "order by cf.name limit $4",
        org_id, dataset_code, value_field, MAX_ITEMS)
    if not rows:
        return []
    shown = await conn.fetch(
        "select w.id, w.name, w.page_id, w.config->>'value_field' as field "
        "from widgets w where w.dashboard_id=$1 and w.organization_id=$2 "
        "  and w.config->>'dataset_code' = $3 and w.config->>'value_field' = any($4::text[])",
        dashboard_id, org_id, dataset_code, [r["code"] for r in rows])
    by_field = {x["field"]: x for x in shown}
    out = []
    for r in rows:
        item = {"field": r["code"], "name": r["name"]}
        hit = by_field.get(r["code"])
        if hit is not None:
            item["shown_widget_id"] = str(hit["id"])
            item["shown_widget_name"] = hit["name"]
            item["shown_page_id"] = str(hit["page_id"]) if hit["page_id"] else None
        out.append(item)
    return out


async def _dynamics(conn, org_id, dataset_code) -> dict:
    """Можно ли вообще смотреть движение: сколько отчётных периодов есть.

    Отвечаем честным «нет», когда период один: предложить «смотреть в динамике»
    и показать точку на пустом графике — хуже, чем не предлагать.
    """
    if not dataset_code:
        return {"available": False, "periods": 0}
    row = await conn.fetchrow(
        "select count(distinct reporting_period_start) as n, "
        "min(reporting_period_start) as first, max(reporting_period_start) as last "
        "from dataset_releases where organization_id=$1 and code=$2 and status <> 'superseded'",
        org_id, dataset_code)
    n = int(row["n"] or 0)
    return {"available": n > 1, "periods": n,
            "first": str(row["first"]) if row["first"] else None,
            "last": str(row["last"]) if row["last"] else None}
