"""Что изменится на дашбордах, если выпустить эти данные (п. 15).

До сих пор модератор перед кнопкой «Выпустить» видел только замечания к самим
данным (`quality.py`). На вопрос «а что от этого поменяется на экранах у
руководителей» ответа не было вовсе: выпуск делался вслепую, и последствия
обнаруживались уже на дашборде.

Экран отвечает на три вопроса:

  ① **Что станет с цифрами** — по каждой графе: сколько сейчас, сколько станет
     и на сколько изменится.
  ② **Где это увидят** — какие виджеты на каких дашбордах смотрят на эти данные.
  ③ **Что может сломаться** — графы и строки, которые в новом файле ИСЧЕЗЛИ,
     хотя виджеты на них ссылаются. Это и есть «защита от ошибочного выпуска»:
     потеря графы не выглядит ошибкой ни в одном другом месте — виджет просто
     начинает показывать «нет данных».

Два решения, важных для правильности:

**Считаем ТОЙ ЖЕ свёрткой, что и карточка показателя** (`aggregate_series`):
количества складываются, доли усредняются. Иначе предпросмотр обещал бы одно
число, а дашборд показал другое — и спорить пришлось бы уже о предпросмотре.

**Новый выпуск не всегда что-то меняет, и об этом надо сказать прямо.** Виджет
читает ПОСЛЕДНИЙ выпуск, поэтому отчёт задним числом (период раньше уже
выпущенного) на дашборды не попадёт вовсе, а виджеты, закреплённые за другим
срезом, не изменятся никогда. Промолчать здесь значило бы дать человеку
уверенность, которой у него нет.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

# Виджеты, у которых есть ОДНО число: для них можно показать «было → станет».
# У таблицы, матрицы и графиков чисел много, и сводить их к одному нельзя —
# про такие честно пишем «изменится», без цифры.
SINGLE_VALUE_TYPES = {"kpi", "gauge"}

# Где в конфигурации виджета может стоять код графы (тот же список, что в
# аналитике папки: иначе показатель, выведенный полосой «план-факт», числился
# бы неиспользованным).
FIELD_KEYS = ("value_field", "plan_field", "fact_field", "label_field")


def _cfg(raw) -> dict:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return {}
    return raw or {}


def _cfg_fields(cfg: dict) -> set:
    out = {cfg[k] for k in FIELD_KEYS if cfg.get(k)}
    out |= set(cfg.get("value_fields") or [])
    return out


def _uses_code(cfg: dict, code: str) -> bool:
    if cfg.get("dataset_code") == code:
        return True
    return any(s.get("dataset_code") == code for s in (cfg.get("series") or []))


async def release_impact(conn, org_id, *, code: str, period, rows, fields, label_col) -> dict:
    """Предпросмотр последствий выпуска. Данные ещё НЕ в базе — считаем по `rows`."""
    from . import quality

    new_values = quality.values_from_rows(rows, fields, label_col)
    names = {f["field_code"]: f["field_name"] for f in fields}
    period_s = str(period) if period else None

    # Выпуск, который сейчас показывают виджеты, и тот, что будет замещён.
    latest = await conn.fetchrow(
        "select id, reporting_period_start from dataset_releases "
        "where organization_id=$1 and code=$2 and status <> 'superseded' "
        "order by reporting_period_start desc nulls last, created_at desc limit 1", org_id, code)
    same_period = await conn.fetchrow(
        "select id, reporting_period_start, created_at from dataset_releases "
        "where organization_id=$1 and code=$2 and status <> 'superseded' "
        "  and reporting_period_start = $3::text::date limit 1", org_id, code, period_s)

    latest_period = latest["reporting_period_start"] if latest else None
    replaces = bool(same_period)
    # Станут ли эти данные теми, что показывают виджеты. Отчёт задним числом
    # (период раньше уже выпущенного) на дашборды не попадёт — и это надо
    # сказать, а не дать человеку ложную уверенность.
    becomes_current = (
        latest_period is None
        or replaces
        or (period_s is not None and str(latest_period) <= period_s)
    )

    # Значения, которые виджеты показывают СЕЙЧАС: если замещаем период —
    # сравнивать надо с тем выпуском, который замещаем, иначе с последним.
    base_id = same_period["id"] if replaces else (latest["id"] if latest else None)
    old_values = await _release_values(conn, base_id) if base_id else {}

    # Имена граф ПРОШЛОГО выпуска: у исчезнувшей графы имени в новом файле нет,
    # а назвать её по-человечески надо именно там — «графа «…» исчезнет» это
    # главное предупреждение экрана, и код поля в нём бесполезен.
    old_names = await _field_names(conn, org_id, code, {k[1] for k in old_values})
    field_rows = _compare_fields(old_values, new_values, names, old_names)
    lost = [f for f in field_rows if f["gone"]]
    widgets = await _widgets(conn, org_id, code, field_rows, becomes_current, period_s)

    old_rows = sorted({k[0] for k in old_values})
    new_rows = sorted({k[0] for k in new_values})
    return {
        "dataset_code": code,
        "period": period_s,
        "replaces": ({"period": str(same_period["reporting_period_start"]),
                      "created_at": same_period["created_at"].isoformat()} if replaces else None),
        "latest_period": str(latest_period) if latest_period else None,
        "becomes_current": becomes_current,
        "first_release": base_id is None,
        "fields": field_rows,
        "lost_fields": [f["field"] for f in lost],
        "rows": {
            "current": len(old_rows), "next": len(new_rows),
            "added": [r for r in new_rows if r not in old_rows][:10],
            "removed": [r for r in old_rows if r not in new_rows][:10],
        },
        "widgets": widgets,
        "widgets_at_risk": sum(1 for w in widgets if w["at_risk"]),
    }


async def _release_values(conn, rel_id) -> Dict[tuple, float]:
    rows = await conn.fetch(
        "select row_label, canonical_field_code, value_number from dataset_values "
        "where dataset_release_id=$1 and value_number is not null", rel_id)
    return {(r["row_label"] or "", r["canonical_field_code"]): float(r["value_number"]) for r in rows}


async def _field_names(conn, org_id, code: str, codes: set) -> Dict[str, str]:
    """Человеческие имена граф из справочника объекта, которому принадлежит код."""
    if not codes:
        return {}
    rows = await conn.fetch(
        "select cf.code, cf.name from canonical_fields cf "
        "where cf.code = any($1::text[]) and cf.object_id = ("
        "  select object_id from dataset_releases where organization_id=$2 and code=$3 "
        "  order by reporting_period_start desc nulls last limit 1)",
        list(codes), org_id, code)
    return {r["code"]: r["name"] for r in rows}


def _compare_fields(old: Dict[tuple, float], new: Dict[tuple, float],
                    names: Dict[str, str], old_names: Dict[str, str]) -> List[dict]:
    """По каждой графе: сколько сейчас, сколько станет, на сколько изменится.

    Свёртка строк — та же `aggregate_series`, что у карточки показателя:
    количества складываются, доли усредняются и помечаются. Иначе предпросмотр
    обещал бы одно число, а дашборд показал другое.
    """
    from ..dashboards._aggregate import aggregate_series

    codes = sorted({k[1] for k in old} | {k[1] for k in new})
    out: List[dict] = []
    for fc in codes:
        name = names.get(fc) or old_names.get(fc) or fc
        o = [v for k, v in old.items() if k[1] == fc]
        n = [v for k, v in new.items() if k[1] == fc]
        cur, how = aggregate_series(o, name) if o else (None, "sum")
        nxt, _ = aggregate_series(n, name) if n else (None, how)
        delta = (nxt - cur) if (cur is not None and nxt is not None) else None
        out.append({
            "field": fc, "name": name, "how": how,
            "current": cur, "next": nxt, "delta": delta,
            "delta_pct": (delta / cur * 100) if (delta is not None and cur) else None,
            # Графа была в прошлом выпуске, а в этом файле её нет: виджеты,
            # которые на неё смотрят, начнут показывать «нет данных».
            "gone": bool(o) and not n,
            "is_new": bool(n) and not o,
        })
    return out


async def _widgets(conn, org_id, code: str, field_rows: List[dict],
                   becomes_current: bool, period_s: Optional[str]) -> List[dict]:
    """Виджеты, которые смотрят на эти данные, и что с ними станет."""
    rows = await conn.fetch(
        "select w.id, w.name, w.widget_type, w.config, w.page_id, "
        "  d.id as dashboard_id, d.name as dashboard_name, d.publication_status, "
        "  p.name as page_name "
        "from widgets w join dashboards d on d.id=w.dashboard_id "
        "left join dashboard_pages p on p.id=w.page_id "
        "where w.organization_id=$1 and d.publication_status <> 'archived'", org_id)

    by_field = {f["field"]: f for f in field_rows}
    lost = {f["field"] for f in field_rows if f["gone"]}
    out: List[dict] = []
    for r in rows:
        cfg = _cfg(r["config"])
        if not _uses_code(cfg, code):
            continue
        used = _cfg_fields(cfg)
        pinned = cfg.get("period")
        # Закреплённый срез меняется, только если выпускают ЕГО период.
        if pinned and str(pinned) != (period_s or ""):
            changes, note = False, f"не изменится — закреплён за {_ru(str(pinned))}"
        elif not becomes_current:
            changes, note = False, "не изменится — на дашборде останется более свежий отчёт"
        else:
            changes, note = True, None

        at_risk = bool(used & lost)
        item = {
            "widget_id": str(r["id"]), "name": r["name"], "type": r["widget_type"],
            "dashboard_id": str(r["dashboard_id"]), "dashboard": r["dashboard_name"],
            "page": r["page_name"], "page_id": str(r["page_id"]) if r["page_id"] else None,
            "published": r["publication_status"] == "published",
            "changes": changes, "note": note,
            "at_risk": at_risk,
            "lost_fields": sorted(used & lost),
            "current": None, "next": None, "delta": None,
        }
        # Одно число — показываем «было → станет». У таблиц и графиков чисел
        # много, сводить их к одному нельзя.
        vf = cfg.get("value_field")
        if changes and r["widget_type"] in SINGLE_VALUE_TYPES and vf and vf in by_field:
            f = by_field[vf]
            item.update(current=f["current"], next=f["next"], delta=f["delta"])
        out.append(item)
    out.sort(key=lambda w: (not w["at_risk"], w["dashboard"] or "", w["page"] or "", w["name"] or ""))
    return out


def _ru(iso: str) -> str:
    parts = iso[:10].split("-")
    return f"{parts[2]}.{parts[1]}.{parts[0]}" if len(parts) == 3 else iso
