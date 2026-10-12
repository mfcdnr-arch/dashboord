"""Порог показателя (норма) — один на графу формы, а не на виджет.

«Время ожидания больше 30 минут — проблема» — свойство ПОКАЗАТЕЛЯ. Если
вписывать его в каждый виджет (карточку, рейтинг, таблицу, динамику), при
первой правке пороги разойдутся, и одно и то же число окажется в карточке
красным, а в таблице зелёным. Поэтому порог живёт у графы
(`canonical_fields.norm`, миграция 064), а виджеты применяют его здесь, в одной
точке, после расчёта. Правка порога сбрасывает кэш данных виджетов — всё
пересчитывается само.

Правила, которые нельзя ослаблять:

* **Свои пороги виджета сильнее.** Если у виджета заданы `config.alerts`,
  норма графы его не трогает: человек настроил виджет нарочно.
* **Направление — от смысла графы.** У длительности «меньше — лучше»
  (проблема — от порога и выше), у остальных по умолчанию «больше — лучше».
* **Свод нескольких граф порог не получает.** Норма — про одну графу; у суммы
  ожиданий по разным графам её нет.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from ... import cache
from ...plural import plural
from ..audit import service as audit
from ..ingestion.analyze import DURATION_UNIT, fmt_duration
from ._base import DashboardError

LEVEL_COLOR = {"danger": "var(--alert-danger)", "warn": "var(--alert-warn)", "good": "var(--alert-good)"}
LEVEL_WORD = {"danger": "проблема", "warn": "внимание", "good": "в норме"}

# Виды, у которых строки сравниваются с порогом поштучно.
_ROW_TYPES = {"ranked", "spark_table"}


def _jsonb(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return None
    return v


def default_direction(unit: Optional[str]) -> str:
    return "lower" if unit == DURATION_UNIT else "higher"


def level(value, norm: Optional[dict]) -> Optional[str]:
    """Уровень значения относительно нормы: danger / warn / good, None — судить не о чем."""
    if value is None or not norm:
        return None
    warn, danger = norm.get("warn"), norm.get("danger")
    if warn is None and danger is None:
        return None
    v = float(value)
    if norm.get("direction") == "higher":
        if danger is not None and v <= danger:
            return "danger"
        if warn is not None and v <= warn:
            return "warn"
        return "good"
    if danger is not None and v >= danger:
        return "danger"
    if warn is not None and v >= warn:
        return "warn"
    return "good"


def fmt_value(v, unit: Optional[str]) -> str:
    if v is None:
        return "—"
    if unit == DURATION_UNIT:
        return fmt_duration(v)
    n = float(v)
    s = f"{int(n):,}" if n.is_integer() else f"{n:,.2f}"
    return s.replace(",", " ").replace(".", ",") + (f" {unit}" if unit else "")


def describe(norm: dict, unit: Optional[str]) -> str:
    """«внимание от 20 мин, проблема от 30 мин» — как порог читается человеком."""
    side = "от" if norm.get("direction") != "higher" else "до"
    parts = []
    if norm.get("warn") is not None:
        parts.append(f"внимание {side} {fmt_value(norm['warn'], unit)}")
    if norm.get("danger") is not None:
        parts.append(f"проблема {side} {fmt_value(norm['danger'], unit)}")
    return ", ".join(parts)


async def dataset_object(conn, org_id, dataset_code: str):
    return await conn.fetchval(
        "select object_id from dataset_releases where organization_id=$1 and code=$2 "
        "and object_id is not null order by reporting_period_start desc nulls last limit 1",
        org_id, dataset_code)


async def field_norms(conn, org_id, dataset_code: str) -> dict:
    """{код графы → {name, unit, norm}} по графам формы с единицей или порогом."""
    obj = await dataset_object(conn, org_id, dataset_code)
    if obj is None:
        return {}
    rows = await conn.fetch(
        "select code, name, unit, norm from canonical_fields where object_id=$1 "
        "and (norm is not null or unit is not null)", obj)
    return {r["code"]: {"name": r["name"], "unit": r["unit"], "norm": _jsonb(r["norm"])} for r in rows}


def _widget_fields(wtype: str, cfg: dict, res: dict) -> list:
    """Графы, которые показывает виджет (без сводов нескольких граф)."""
    if cfg.get("measure"):
        return []  # рейтинг по мере — свод нескольких граф
    cross = cfg.get("cross")
    if cross is not None and not _cross_bound(cross, cfg):
        # «Талонов на окно» — не «талоны»: порог графы-талонов к отношению
        # не относится. Порог получает только показатель, ЯВНО привязанный к
        # графе того же смысла (взвешенное ожидание ↔ ожидание).
        return []
    if wtype == "table":
        return list(res.get("columns") or [])
    one = cfg.get("value_field")
    many = cfg.get("value_fields") or []
    return [one] if one else list(many)


def _cross_bound(cross: dict, cfg: dict) -> bool:
    if cross.get("norm_field"):
        return cross["norm_field"] == cfg.get("value_field")
    # Виджеты, собранные до 12.10.2026 (без явной привязки): взвешенное
    # время — в минутах, как и его графа; у отношений единицы нет.
    return bool(cross.get("unit")) and cross.get("unit") == DURATION_UNIT


async def apply_norms(conn, org_id, wtype: str, cfg: dict, res: dict) -> dict:
    """Подкрасить результат виджета по нормам граф и сказать о них.

    В результат кладётся `norm_fields` — какие графы виджета можно снабдить
    порогом (и какой стоит сейчас): по нему экран рисует строку «Порог: …» с
    кнопкой правки. Длительность получает строку и без порога — ради неё всё и
    затевалось; прочие графы — только когда порог уже задан.
    """
    code = cfg.get("dataset_code")
    if not code or not isinstance(res, dict):
        return res
    norms = await field_norms(conn, org_id, code)
    fields = [f for f in _widget_fields(wtype, cfg, res) if f in norms]
    # Виджет по ОДНОЙ графе времени печатает её «ч мин с», даже если единицу в
    # настройке виджета не указали (собран руками, а не мастером): иначе
    # матрица ожидания показывала «14,05» вместо «14 мин 3 с» (12.10.2026).
    if (len(fields) == 1 and wtype != "table" and not cfg.get("unit") and not res.get("unit")
            and norms[fields[0]]["unit"] == DURATION_UNIT):
        res["unit"] = DURATION_UNIT
    shown = [f for f in fields if norms[f]["norm"] or norms[f]["unit"] == DURATION_UNIT]
    if not shown:
        return res
    res["norm_fields"] = [
        {"dataset_code": code, "field": f, "name": norms[f]["name"], "unit": norms[f]["unit"],
         "norm": norms[f]["norm"], "direction": (norms[f]["norm"] or {}).get("direction")
         or default_direction(norms[f]["unit"]),
         "text": describe(norms[f]["norm"], norms[f]["unit"]) if norms[f]["norm"] else None}
        for f in shown]
    if cfg.get("alerts"):
        return res  # свои пороги виджета сильнее нормы графы
    active = {f: norms[f] for f in shown if norms[f]["norm"]}
    if not active:
        return res

    if wtype in ("kpi", "gauge", "dynamics") and len(fields) == 1 and fields[0] in active:
        f = active[fields[0]]
        measure = res.get("value") if wtype != "dynamics" else ((res.get("values") or [None])[-1])
        lvl = level(measure, f["norm"])
        if lvl:
            res["alert"] = {"level": lvl, "color": LEVEL_COLOR[lvl], "bg": None,
                            "label": f"{LEVEL_WORD[lvl]}: порог — {describe(f['norm'], f['unit'])}",
                            "measure": measure, "source": "norm"}
        if wtype == "dynamics":
            res["norm_lines"] = {k: f["norm"].get(k) for k in ("warn", "danger") if f["norm"].get(k) is not None}
        return res

    if wtype in _ROW_TYPES and len(fields) == 1 and fields[0] in active:
        f = active[fields[0]]
        counts = {"danger": 0, "warn": 0, "good": 0}
        for r in res.get("rows") or []:
            v = r.get("value") if wtype == "ranked" else r.get("last")
            lvl = level(v, f["norm"])
            if lvl:
                r["color"] = LEVEL_COLOR[lvl]
                r["norm_level"] = lvl
                if wtype != "ranked":
                    counts[lvl] += 1
        if wtype == "ranked":
            # Итог — по ВСЕМ строкам формы, а не по показанным верху и низу.
            for v in res.get("values_all") or []:
                lvl = level(v, f["norm"])
                if lvl:
                    counts[lvl] += 1
        res["norm_summary"] = _summary(counts, f)
        return res

    if wtype == "table":
        styles = {"danger": {"color": "var(--alert-danger)", "bg": "var(--alert-danger-bg)"},
                  "warn": {"color": "var(--alert-warn)", "bg": "var(--alert-warn-bg)"},
                  "good": {"color": "var(--alert-good)", "bg": "var(--alert-good-bg)"}}
        marked = False
        for r in res.get("rows") or []:
            for c, f in active.items():
                lvl = level(r.get(c), f["norm"])
                if lvl and lvl != "good":  # таблицу красим только там, где есть о чём сказать
                    r.setdefault("__fmt", {})[c] = lvl
                    marked = True
        if marked:
            res["alert_styles"] = {**(res.get("alert_styles") or {}), **styles}
        return res

    if wtype == "matrix" and res.get("by") != "fields" and len(fields) == 1 and fields[0] in active:
        f = active[fields[0]]
        # Уровень кладётся В САМУ строку: матрицу сортируют кликом по
        # заголовку, и отдельный список по индексам после сортировки красил
        # бы чужие клетки.
        cells = []
        for r in res.get("rows") or []:
            r["norm_levels"] = [level(v, f["norm"]) for v in (r.get("values") or [])]
            cells.append(r["norm_levels"])
        res["norm_cells"] = cells
        res["norm_summary"] = _matrix_summary(cells, f)
    return res


def _matrix_summary(cells: list, f: dict) -> Optional[str]:
    """По последнему столбцу матрицы: сколько строк выше порога сейчас."""
    last = [row[-1] for row in cells if row]
    if not any(last):
        return None
    counts = {k: sum(1 for x in last if x == k) for k in ("danger", "warn", "good")}
    return "в последнем отчёте — " + _summary(counts, f)


def _summary(counts: dict, f: dict) -> str:
    unit = f["unit"]
    n = f["norm"]
    side = "выше" if n.get("direction") != "higher" else "ниже"
    parts = []
    if n.get("danger") is not None:
        parts.append(f"{side} порога {fmt_value(n['danger'], unit)}: {counts['danger']}")
    if n.get("warn") is not None:
        parts.append(f"внимание (от {fmt_value(n['warn'], unit)}): {counts['warn']}")
    parts.append(f"в норме: {counts['good']}")
    return " · ".join(parts)


# --- Правка -----------------------------------------------------------------

async def set_norm(conn, org_id, user_id, dataset_code: str, field: str,
                   warn: Optional[float], danger: Optional[float],
                   direction: Optional[str] = None) -> dict:
    obj = await dataset_object(conn, org_id, dataset_code)
    if obj is None:
        raise DashboardError("Форма не найдена")
    row = await conn.fetchrow("select id, name, unit, norm from canonical_fields where object_id=$1 and code=$2",
                              obj, field)
    if row is None:
        raise DashboardError("Графа не найдена")
    if direction not in (None, "lower", "higher"):
        raise DashboardError("Направление: lower или higher")
    direction = direction or default_direction(row["unit"])
    for v in (warn, danger):
        if v is not None and v < 0:
            raise DashboardError("Порог не может быть отрицательным")
    if warn is not None and danger is not None:
        if direction == "lower" and warn >= danger:
            raise DashboardError("«Внимание» должно наступать раньше «проблемы»: порог внимания меньше порога проблемы")
        if direction == "higher" and warn <= danger:
            raise DashboardError("«Внимание» должно наступать раньше «проблемы»: порог внимания больше порога проблемы")
    before = _jsonb(row["norm"])
    norm = None if warn is None and danger is None else {
        "warn": warn, "danger": danger, "direction": direction,
        "updated_at": datetime.now(timezone.utc).isoformat(), "updated_by": str(user_id) if user_id else None}
    await conn.execute("update canonical_fields set norm=$2::jsonb where id=$1",
                       row["id"], json.dumps(norm) if norm else None)
    await audit.write_event(conn, org_id, user_id, "update", "field_norm", str(row["id"]),
                            old_data={"field": field, "norm": before},
                            new_data={"field": field, "name": row["name"], "norm": norm})
    # Все виджеты по этой графе — и карточки, и рейтинги, и таблицы — должны
    # пересчитаться сразу, а не через полминуты по истечении кэша.
    await cache.delete_prefix("wd:")
    return {"field": field, "name": row["name"], "unit": row["unit"], "norm": norm,
            "text": describe(norm, row["unit"]) if norm else None}


async def list_norms(conn, org_id) -> list:
    """Все графы, у которых порог задан или напрашивается (длительность), —
    для общего списка «Пороги показателей» в «Настройках».

    Поправить порог можно и из любого виджета, но администратору нужен ОДИН
    экран, где видно всё сразу: иначе, чтобы узнать, какие пороги вообще
    действуют, пришлось бы обойти все дашборды.
    """
    rows = await conn.fetch(
        "select cf.code, cf.name, cf.unit, cf.norm, o.name as object_name, "
        " coalesce((select dr.code from dataset_release_fields rf "
        "    join dataset_releases dr on dr.id = rf.dataset_release_id "
        "   where dr.object_id = cf.object_id and rf.canonical_field_code = cf.code "
        "   order by dr.reporting_period_start desc nulls last limit 1), "
        # Выпуски, у которых графы не объявлены (загружены до 23.09.2026 или
        # строками), — по самим значениям; дороже, поэтому только запасным путём.
        "  (select dr.code from dataset_releases dr where dr.object_id = cf.object_id "
        "     and exists(select 1 from dataset_values dv where dv.dataset_release_id = dr.id "
        "                and dv.canonical_field_code = cf.code) "
        "   order by dr.reporting_period_start desc nulls last limit 1)) as dataset_code "
        "from canonical_fields cf join objects o on o.id = cf.object_id "
        "where o.organization_id = $1 and (cf.norm is not null or cf.unit = $2) "
        "order by o.name, cf.name", org_id, DURATION_UNIT)
    out = []
    for r in rows:
        if not r["dataset_code"]:
            continue  # графа без выпусков — порог применить не к чему
        norm = _jsonb(r["norm"])
        out.append({"dataset_code": r["dataset_code"], "field": r["code"], "name": r["name"],
                    "unit": r["unit"], "object_name": r["object_name"], "norm": norm,
                    "direction": (norm or {}).get("direction") or default_direction(r["unit"]),
                    "text": describe(norm, r["unit"]) if norm else None,
                    "updated_at": (norm or {}).get("updated_at")})
    return out


# --- «На что посмотреть» ----------------------------------------------------

def norm_warnings(values: dict, norms: dict) -> list:
    """Замечания «выше порога» по последнему отчёту: {(строка, графа): значение}."""
    out = []
    for code, f in norms.items():
        n = f.get("norm")
        if not n or n.get("danger") is None:
            continue
        rows = [(lab, v) for (lab, c), v in values.items() if c == code and lab]
        bad = sorted(((lab, v) for lab, v in rows if level(v, n) == "danger"),
                     key=lambda x: -x[1] if n.get("direction") != "higher" else x[1])
        if not bad:
            continue
        side = "выше" if n.get("direction") != "higher" else "ниже"
        examples = ", ".join(f"{lab} — {fmt_value(v, f['unit'])}" for lab, v in bad[:3])
        out.append({
            "code": "norm_exceeded", "count": len(bad),
            "message": (f"«{f['name']}» {side} порога {fmt_value(n['danger'], f['unit'])} "
                        f"у {len(bad)} {plural(len(bad), 'строки', 'строк', 'строк')} из {len(rows)}: {examples}"
                        + (f" и ещё {len(bad) - 3}" if len(bad) > 3 else "") + "."),
        })
    return out
