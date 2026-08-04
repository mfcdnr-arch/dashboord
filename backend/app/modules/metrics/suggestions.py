"""Рекомендательная система дашбордов, часть B (2026-08-04): предложения
ПРОИЗВОДНЫХ метрик между уже существующими метриками.

БЕЗ ИИ — DSL уже умеет разность/долю/оконные функции (A-B, PERCENT_OF,
PERIOD_COMPARE, RUNNING_TOTAL, PLAN_FACT_PCT); здесь только правило-эвристика,
которая находит подходящие пары/метрики среди уже существующих и черновит
текст формулы. Пользователь отмечает нужные — принятое предложение создаётся
как метрика в статусе draft и проходит обычный цикл проверки draft→
validated→approved (см. metrics/service.py:create_version).

Область действия (подтверждена пользователем в чате 2026-08-04) — объединение
двух видов: «в рамках объекта» (метрики, чьи формулы используют датасеты
объекта) и «в рамках открытого дашборда» (метрики, на которые ссылаются
виджеты дашборда). Обе резолвятся из ОДНОГО параметра dashboard_id — объект
подтягивается через dashboards.folder_id→folders.object_id, если дашборд
лежит в папке объекта (волна D); если нет — работает только dashboard-scope.

Одобренные пользователем 7 типов (2026-07-31, только эти — остальное из
ревью-списка сознательно не реализуем):
1) разница A-B; 2) доля/процент A от B; 3) период-к-периоду; 4) год к году;
5) накопительный итог; 6) план/факт-пара по названию → % выполнения;
7) отклонение от цели (только для метрик, использованных в KPI/gauge-виджете
   с заданной целью — вне контекста конкретного виджета «цели» у метрики нет).
"""
from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from .parser import extract_dependencies

MAX_PAIR_SUGGESTIONS = 10  # разница+доля порознь — иначе N² быстро перегружает список
MAX_TOTAL_SUGGESTIONS = 30

_PLAN_WORDS = ("план", "plan")
_FACT_WORDS = ("факт", "fact")


def _ast(row_value) -> Optional[dict]:
    if row_value is None:
        return None
    if isinstance(row_value, str):
        return json.loads(row_value) if row_value else None
    return row_value


def _cfg(row_value) -> dict:
    if row_value is None:
        return {}
    if isinstance(row_value, str):
        return json.loads(row_value) if row_value else {}
    return row_value


def _norm_formula(expr: str) -> str:
    return re.sub(r"\s+", "", expr or "")


def _plan_fact_key(code: str, name: str) -> Optional[tuple]:
    """('plan'|'fact', остаток_названия_без_план/факт-слова) — для пары план_X/факт_X."""
    hay = f"{code} {name}".lower()
    is_plan = any(w in hay for w in _PLAN_WORDS)
    is_fact = any(w in hay for w in _FACT_WORDS)
    if is_plan == is_fact:
        return None  # ни то, ни то, либо оба сразу — не пара
    base = hay
    for w in (*_PLAN_WORDS, *_FACT_WORDS):
        base = base.replace(w, "")
    base = re.sub(r"[\s_\-]+", "", base)
    if not base:
        return None
    return ("plan" if is_plan else "fact", base)


async def _org_metrics(conn, org_id) -> List[dict]:
    """Все метрики организации + датасеты, от которых зависит их ЛУЧШАЯ версия
    (approved→validated→draft, как и везде в проекте — см. list_data_sources)."""
    rows = await conn.fetch(
        "select m.id, m.code, m.name, "
        "(select mv.id from metric_versions mv where mv.metric_id=m.id "
        " order by (case mv.status when 'approved' then 0 when 'validated' then 1 else 2 end), "
        " mv.version_no desc limit 1) as best_version_id "
        "from metrics m where m.organization_id=$1", org_id)
    out = []
    for r in rows:
        if r["best_version_id"] is None:
            continue
        v = await conn.fetchrow(
            "select formula_expression, formula_ast, unit from metric_versions where id=$1", r["best_version_id"])
        ast = _ast(v["formula_ast"])
        datasets = set(extract_dependencies(ast)["datasets"]) if ast else set()
        out.append({"id": str(r["id"]), "code": r["code"], "name": r["name"], "unit": v["unit"],
                    "formula": v["formula_expression"], "datasets": datasets, "target": None})
    return out


async def _object_dataset_codes(conn, org_id, object_id: str) -> set:
    rows = await conn.fetch(
        "select distinct code from dataset_releases where organization_id=$1 and object_id=$2::uuid "
        "and status<>'superseded'", org_id, object_id)
    return {r["code"] for r in rows}


async def _dashboard_object_id(conn, org_id, dashboard_id: str) -> Optional[str]:
    row = await conn.fetchrow(
        "select fo.object_id from dashboards d left join folders fo on fo.id=d.folder_id "
        "where d.id=$1::uuid and d.organization_id=$2", dashboard_id, org_id)
    return str(row["object_id"]) if row and row["object_id"] else None


async def _dashboard_metric_codes_and_targets(conn, org_id, dashboard_id: str) -> Dict[str, Optional[float]]:
    """Коды метрик, на которые ссылаются виджеты дашборда (metric_code/plan_metric/
    fact_metric) → цель (config.target), если задана на KPI/gauge-виджете."""
    rows = await conn.fetch(
        "select w.config from widgets w join dashboard_pages p on p.id=w.page_id "
        "where p.dashboard_id=$1::uuid and w.organization_id=$2", dashboard_id, org_id)
    out: Dict[str, Optional[float]] = {}
    for r in rows:
        cfg = _cfg(r["config"])
        target = cfg.get("target")
        for key in ("metric_code", "plan_metric", "fact_metric"):
            code = cfg.get(key)
            if not code:
                continue
            if code not in out or out[code] is None:
                out[code] = target if key == "metric_code" else None
    return out


_TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
})


def _slug(text: str) -> str:
    s = text.lower().translate(_TRANSLIT)
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s[:60] or "metric"


def _assign_codes(specs: List[dict], existing_codes: set) -> None:
    """Черновой код новой метрики — слаг от названия предложения, с числовым
    суффиксом при коллизии (проверка и против БД, и внутри самого пакета)."""
    used = set(existing_codes)
    for spec in specs:
        base = _slug(f"{spec['type']}_{spec['name']}")
        code, i = base, 2
        while code in used:
            code = f"{base}_{i}"
            i += 1
        used.add(code)
        spec["code"] = code


async def _dataset_multi_period(conn, org_id, dataset_code: str) -> bool:
    n = await conn.fetchval(
        "select count(distinct reporting_period_start) from dataset_releases "
        "where organization_id=$1 and code=$2 and status<>'superseded'", org_id, dataset_code)
    return (n or 0) > 1


async def suggest_derived_metrics(conn, org_id, dashboard_id: str) -> dict:
    all_metrics = await _org_metrics(conn, org_id)
    by_code = {m["code"]: m for m in all_metrics}

    dash_codes = await _dashboard_metric_codes_and_targets(conn, org_id, dashboard_id)
    object_id = await _dashboard_object_id(conn, org_id, dashboard_id)
    obj_ds_codes = await _object_dataset_codes(conn, org_id, object_id) if object_id else set()

    candidates: Dict[str, dict] = {}
    for code, target in dash_codes.items():
        m = by_code.get(code)
        if m is None:
            continue
        c = dict(m)
        c["target"] = target
        candidates[code] = c
    for m in all_metrics:
        if m["code"] in candidates:
            continue
        if obj_ds_codes and (m["datasets"] & obj_ds_codes):
            candidates[m["code"]] = m

    existing_formulas = {_norm_formula(m["formula"]) for m in all_metrics}
    multi_period_cache: Dict[str, bool] = {}

    async def has_multi_period(m: dict) -> bool:
        for ds in m["datasets"]:
            if ds not in multi_period_cache:
                multi_period_cache[ds] = await _dataset_multi_period(conn, org_id, ds)
            if multi_period_cache[ds]:
                return True
        return False

    specs: List[dict] = []

    def add(spec_type: str, name: str, formula: str, unit: Optional[str], based_on: List[str]):
        if len(specs) >= MAX_TOTAL_SUGGESTIONS:
            return
        if _norm_formula(formula) in existing_formulas:
            return  # уже есть метрика с такой же формулой — не повторяем
        specs.append({"type": spec_type, "name": name, "formula": formula, "unit": unit, "based_on": based_on})

    # 3/4/5 — единичные (период-к-периоду / год к году / накопительный итог)
    for c in candidates.values():
        if not await has_multi_period(c):
            continue
        add("period_compare", f"{c['name']}: период-к-периоду",
            f"PERIOD_COMPARE(metric('{c['code']}'), 'month')", c["unit"], [c["code"]])
        add("yoy", f"{c['name']}: год к году",
            f"PERIOD_COMPARE(metric('{c['code']}'), 'year')", c["unit"], [c["code"]])
        add("running_total", f"{c['name']}: накопительный итог",
            f"RUNNING_TOTAL(metric('{c['code']}'), grain='month')", c["unit"], [c["code"]])

    # 7 — отклонение от цели (только там, где виджет реально задал target)
    for c in candidates.values():
        if c["target"] is None or not c["target"]:
            continue
        add("deviation", f"{c['name']}: отклонение от цели",
            f"(metric('{c['code']}') - {c['target']}) / {c['target']} * 100", "%", [c["code"]])

    # 6 — план/факт-пара по названию
    plan_by_base: Dict[str, dict] = {}
    fact_by_base: Dict[str, dict] = {}
    for c in candidates.values():
        pk = _plan_fact_key(c["code"], c["name"])
        if pk is None:
            continue
        kind, base = pk
        (plan_by_base if kind == "plan" else fact_by_base)[base] = c
    for base, plan_m in plan_by_base.items():
        fact_m = fact_by_base.get(base)
        if fact_m is None or fact_m["code"] == plan_m["code"]:
            continue
        add("plan_fact", f"{base}: % выполнения",
            f"PLAN_FACT_PCT(metric('{plan_m['code']}'), metric('{fact_m['code']}'))", "%",
            [plan_m["code"], fact_m["code"]])

    # 1/2 — разница и доля между «родственными» метриками (общий датасет-источник)
    codes_sorted = sorted(candidates.keys())
    pair_count = 0
    for i, ca in enumerate(codes_sorted):
        if pair_count >= MAX_PAIR_SUGGESTIONS:
            break
        a = candidates[ca]
        for cb in codes_sorted[i + 1:]:
            if pair_count >= MAX_PAIR_SUGGESTIONS:
                break
            b = candidates[cb]
            if not (a["datasets"] & b["datasets"]):
                continue
            add("diff", f"{a['name']} − {b['name']}",
                f"metric('{a['code']}') - metric('{b['code']}')",
                a["unit"] if a["unit"] == b["unit"] else None, [a["code"], b["code"]])
            add("share", f"{a['name']}, % от {b['name']}",
                f"PERCENT_OF(metric('{b['code']}'), metric('{a['code']}'))", "%", [a["code"], b["code"]])
            pair_count += 1

    _assign_codes(specs, set(by_code.keys()))
    return {"specs": specs, "candidates_count": len(candidates)}
