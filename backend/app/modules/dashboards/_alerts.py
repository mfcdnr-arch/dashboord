"""KPI-алерты + условное форматирование виджетов (вынесено из service.py).

Пороги задаются в config виджета: config["alerts"] = [
  {level: danger|warn|good, op: lt|lte|gt|gte|eq|between|outside,
   value: number, value2?: number, label?: str}
]  — первое сработавшее правило определяет цвет/подпись.
Что сравнивается (config["alert_on"]):
  kpi        → значение (value, всегда);
  plan_fact  → pct (по умолч.) | fact | delta | plan;
  dynamics   → last (по умолч.) | change | change_pct.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

_ALERT_STYLES = {
    "danger": {"color": "#a32d2d", "bg": "#fcebeb"},
    # Оранжевый — четвёртая ступень, добавлена под шкалу выполнения плана
    # (<50 / 50–70 / 70–85 / ≥85 %). Трёх цветов для неё не хватает: между
    # «провалено» и «внимание» есть разница, которую руководитель хочет видеть.
    "poor":   {"color": "#b35309", "bg": "#fdf0e3"},
    "warn":   {"color": "#9a6a00", "bg": "#fff4e0"},
    "good":   {"color": "#0f6e56", "bg": "#eaf5f0"},
}
_ALERT_OP_TXT = {"lt": "<", "lte": "≤", "gt": ">", "gte": "≥", "eq": "=",
                 "between": "в диапазоне", "outside": "вне диапазона"}


def _cfg(row) -> Dict[str, Any]:
    c = row["config"]
    if isinstance(c, str):
        return json.loads(c) if c else {}
    return c or {}


def _alert_measure(widget_type: str, cfg: dict, data: dict):
    if widget_type == "kpi":
        return data.get("value")
    if widget_type == "plan_fact":
        return data.get(cfg.get("alert_on") or "pct")
    if widget_type == "dynamics":
        key = cfg.get("alert_on") or "last"
        if key == "last":
            vals = data.get("values") or []
            return vals[-1] if vals else None
        return data.get(key)  # change | change_pct
    return None


def _alert_match(measure, rule: dict) -> bool:
    if measure is None:
        return False
    op = rule.get("op")
    try:
        m = float(measure)
        v = float(rule["value"]) if rule.get("value") is not None else None
        v2 = float(rule["value2"]) if rule.get("value2") is not None else None
    except (TypeError, ValueError, KeyError):
        return False
    if op == "lt":      return v is not None and m < v
    if op == "lte":     return v is not None and m <= v
    if op == "gt":      return v is not None and m > v
    if op == "gte":     return v is not None and m >= v
    if op == "eq":      return v is not None and m == v
    if op == "between": return v is not None and v2 is not None and v <= m <= v2
    if op == "outside": return v is not None and v2 is not None and (m < v or m > v2)
    return False


def evaluate_alert(widget_type: str, cfg: dict, data: dict) -> Optional[dict]:
    rules = cfg.get("alerts") or []
    if not rules:
        return None
    measure = _alert_measure(widget_type, cfg, data)
    for rule in rules:
        if _alert_match(measure, rule):
            lvl = rule.get("level", "danger")
            st = _ALERT_STYLES.get(lvl, _ALERT_STYLES["danger"])
            label = rule.get("label")
            if not label:
                op = _ALERT_OP_TXT.get(rule.get("op"), rule.get("op"))
                if rule.get("op") in ("between", "outside"):
                    label = f"{op} {rule.get('value')}…{rule.get('value2')}"
                else:
                    label = f"{op} {rule.get('value')}"
            return {"level": lvl, "color": st["color"], "bg": st["bg"],
                    "label": label, "measure": measure}
    return None


# --- Условное форматирование ЯЧЕЕК таблицы (п. 2 списка предложений) ---------
#
# Правила ТЕ ЖЕ, что у карточки: та же `config["alerts"]`, тот же `_alert_match`
# и та же палитра `_ALERT_STYLES`. Своей логики у таблицы нет и быть не должно —
# иначе одно и то же число красилось бы в карточке одним цветом, а в таблице
# другим, и спорить пришлось бы уже о цветах, а не о данных.
#
# Что размечать, говорит `config["cell_format"]` — {код столбца: 'alert'|'bar'}:
#   'alert' — цвет по порогам (считается ЗДЕСЬ, на сервере);
#   'bar'   — полоска по величине; она считается на клиенте от максимума
#             столбца, потому что никакого правила в ней нет — только
#             соотношение чисел, которые и так уже пришли.


def cell_alert_levels(cfg: dict, rows: list) -> None:
    """Проставляет строкам таблицы уровень порога по нужным столбцам.

    Уровень кладётся В САМУ СТРОКУ (`row["__fmt"] = {код: уровень}`), а не
    отдельным массивом по индексам: таблицу на экране сортируют и фильтруют,
    и разметка, привязанная к номеру строки, разъехалась бы с данными после
    первого же клика по заголовку.

    Цвета отдаются один раз на виджет (`alert_styles`), а не в каждой ячейке:
    на таблице районов это тысячи повторов одного и того же.
    """
    fmt = cfg.get("cell_format") or {}
    fields = [f for f, mode in fmt.items() if mode == "alert"]
    rules = cfg.get("alerts") or []
    if not fields or not rules:
        return
    for row in rows:
        marks = {}
        for f in fields:
            for rule in rules:
                if _alert_match(row.get(f), rule):
                    marks[f] = rule.get("level", "danger")
                    break
        if marks:
            row["__fmt"] = marks


def alert_styles() -> Dict[str, Any]:
    """Палитра уровней — чтобы клиент не держал свою копию цветов."""
    return {lvl: dict(st) for lvl, st in _ALERT_STYLES.items()}
