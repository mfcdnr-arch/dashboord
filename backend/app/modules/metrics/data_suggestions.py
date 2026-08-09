"""Что можно посчитать по САМИМ ДАННЫМ (2026-08-09).

Заказчик: «пусть система сама предлагает, какие метрики можно применить, из
анализа файла и дашбордов» — по образцу разбора, который до этого делался
руками: «есть отправленные и доставленные уведомления, есть план до 1 сентября —
напрашиваются доля доставленных, выполнение плана, прирост к прошлой неделе и
конверсия».

Отличие от suggestions.py: тот строит производные от УЖЕ ЗАВЕДЁННЫХ метрик
(metric('код')), а здесь показателей может не быть вовсе — разбираются имена
СТОЛБЦОВ распознанного файла, и формулы собираются прямо на field().

БЕЗ ИИ: разбор имени по разделителям госформ и словари ключевых слов.
Имена в формах МФЦ устроены единообразно:
    «Количество отправленных уведомлений … (из АИС МФЦ в Notify) · Факт · нарастающим итогом**»
     └─ показатель ──────────────────────────────────────────────┘  └роль┘  └── разрез ──┘
Отсюда берутся: показатель (по нему ищутся пары), роль (план/факт) и разрез
(нарастающим итогом / текущий месяц / за неделю). Пары сопоставляются ТОЛЬКО
внутри одного разреза — иначе получится «доставленные за неделю от отправленных
нарастающим итогом», то есть бессмыслица с виду правдоподобным числом.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .suggestions import _assign_codes, _norm_formula

MAX_SUGGESTIONS = 40

# Роль столбца в форме.
_PLAN_RE = re.compile(r"\bплан\b", re.I)
_FACT_RE = re.compile(r"\bфакт\b", re.I)

# Пары «целое → часть»: (слова целого, слова части, как назвать, что это значит).
# Порядок важен: первая подошедшая пара выигрывает.
_FUNNEL_PAIRS = [
    (("отправленн", "направленн", "выгруженн"), ("доставленн", "врученн", "полученн"),
     "Доля доставленных", "какая часть отправленного дошла до адресата"),
    (("обращени", "обратилось", "заявлен"), ("записавших", "записал", "зарегистрирова"),
     "Конверсия обращений в записи", "какая часть обратившихся дошла до записи"),
    (("всего", "итого", "общее количество"), ("успешно", "положительн", "результативн"),
     "Доля успешных", "какая часть от общего числа завершилась успехом"),
    (("всего", "итого", "общее количество"), ("отказ", "ошибк", "неуспешн"),
     "Доля отказов", "какая часть от общего числа — отказы и ошибки"),
]


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("*", "")).strip()


def _split_name(name: str) -> Dict[str, str]:
    """Имя столбца → {subject, role, slice}. Разделитель госформ — « · »."""
    parts = [_clean(p) for p in re.split(r"\s*·\s*", name or "") if _clean(p)]
    if not parts:
        return {"subject": _clean(name), "role": "", "slice": ""}
    subject, role, slc = parts[0], "", ""
    for p in parts[1:]:
        if _PLAN_RE.search(p) or _FACT_RE.search(p):
            role = "plan" if _PLAN_RE.search(p) else "fact"
            # «План (до 1 сентября 2026 г.)» — срок остаётся частью разреза плана
            rest = _clean(_PLAN_RE.sub("", _FACT_RE.sub("", p)))
            if rest and not slc:
                slc = rest
        elif not slc:
            slc = p
        else:
            slc = f"{slc} {p}"
    return {"subject": subject, "role": role, "slice": slc}


def _subject_key(subject: str) -> str:
    """Ключ показателя для сопоставления пар: без регистра, скобок и пунктуации."""
    s = re.sub(r"\([^)]*\)", " ", (subject or "").lower())
    return re.sub(r"[^а-яёa-z0-9]+", "", s)


def _has(hay: str, words) -> bool:
    low = (hay or "").lower()
    return any(w in low for w in words)


def _is_main_slice(slc: str) -> bool:
    """Основной разрез показателя — «нарастающим итогом» без уточнений.

    В форме у одного показателя обычно три столбца: нарастающим итогом,
    нарастающим итогом (текущий месяц) и за отчётную неделю. План задан
    «до 1 сентября», то есть накопительный, и сравнивать его нужно с общим
    накопительным фактом — иначе «выполнение плана» предлагалось бы дважды,
    причём один раз против месячного среза, что заведомо неверно.
    """
    s = _clean(slc).lower()
    if not s:
        return True
    return "нараст" in s and "месяц" not in s and "недел" not in s


async def _datasets(conn, org_id, dataset_code: Optional[str], object_id: Optional[str]) -> List[dict]:
    where = ["r.organization_id=$1", "r.status<>'superseded'"]
    params: List[Any] = [org_id]
    if dataset_code:
        params.append(dataset_code)
        where.append(f"r.code=${len(params)}")
    if object_id:
        params.append(object_id)
        where.append(f"r.object_id=${len(params)}::uuid")
    rows = await conn.fetch(
        "select r.code, max(r.name) as name, max(r.object_id::text) as object_id, "
        "count(distinct r.reporting_period_start) as periods "
        f"from dataset_releases r where {' and '.join(where)} group by r.code order by max(r.name)",
        *params)
    return [dict(r) for r in rows]


async def _numeric_fields(conn, org_id, code: str) -> List[dict]:
    """Числовые столбцы датасета с человеческими именами из справочника объекта."""
    rows = await conn.fetch(
        "select distinct dv.canonical_field_code as code, "
        "       coalesce(cf.name, dv.canonical_field_code) as name "
        "from dataset_values dv "
        "join dataset_releases r on r.id = dv.dataset_release_id "
        "left join canonical_fields cf on cf.code = dv.canonical_field_code and cf.object_id = r.object_id "
        "where r.organization_id=$1 and r.code=$2 and r.status<>'superseded' and dv.value_number is not null",
        org_id, code)
    return [dict(r) for r in rows]


async def _existing_formulas(conn, org_id) -> set:
    rows = await conn.fetch(
        "select v.formula_expression from metric_versions v "
        "join metrics m on m.id = v.metric_id where m.organization_id=$1", org_id)
    return {_norm_formula(r["formula_expression"]) for r in rows}


def _sum(ds: str, field: str) -> str:
    return f"SUM(field('{ds}','{field}'))"


def _build_specs(ds: dict, fields: List[dict]) -> List[dict]:
    """Правила разбора: что осмысленно посчитать по этому набору столбцов."""
    code = ds["code"]
    multi_period = (ds.get("periods") or 0) > 1
    parsed = []
    for f in fields:
        p = _split_name(f["name"])
        parsed.append({**f, **p, "key": _subject_key(p["subject"])})

    specs: List[dict] = []

    def add(kind: str, name: str, formula: str, unit, why: str, based_on: List[str]):
        specs.append({"type": kind, "name": name, "formula": formula, "unit": unit,
                      "why": why, "based_on": based_on, "dataset_code": code})

    # 1. План/факт одного показателя → выполнение плана и остаток.
    plans = {p["key"]: p for p in parsed if p["role"] == "plan"}
    for p in parsed:
        if p["role"] != "fact" or p["key"] not in plans or not _is_main_slice(p["slice"]):
            continue
        plan = plans[p["key"]]
        add("plan_fact_pct", f"{p['subject']}: выполнение плана, %",
            f"PLAN_FACT_PCT({_sum(code, plan['code'])}, {_sum(code, p['code'])})", "%",
            "есть и план, и факт по одному показателю — видно, успеваем ли к сроку",
            [plan["code"], p["code"]])
        add("plan_remainder", f"{p['subject']}: остаток до плана",
            f"{_sum(code, plan['code'])} - {_sum(code, p['code'])}", None,
            "сколько ещё нужно сделать до планового значения",
            [plan["code"], p["code"]])

    # 2. Воронки «целое → часть» внутри ОДНОГО разреза.
    facts = [p for p in parsed if p["role"] != "plan"]
    for whole_words, part_words, title, why in _FUNNEL_PAIRS:
        for whole in facts:
            if not _has(whole["subject"], whole_words):
                continue
            for part in facts:
                if part["code"] == whole["code"] or not _has(part["subject"], part_words):
                    continue
                if _clean(part["slice"]).lower() != _clean(whole["slice"]).lower():
                    continue  # разные разрезы сравнивать нельзя
                slice_hint = f" ({part['slice']})" if part["slice"] else ""
                add("percent_of", f"{title}{slice_hint}, %",
                    f"PERCENT_OF({_sum(code, whole['code'])}, {_sum(code, part['code'])})", "%",
                    why, [whole["code"], part["code"]])

    # 3. Динамика — только когда выпусков за разные периоды больше одного.
    if multi_period:
        for p in facts:
            if not _is_main_slice(p["slice"]):
                continue  # по месячным и недельным срезам динамика дублировала бы основную
            add("period_delta", f"{p['subject']}: прирост к прошлому периоду",
                f"PERIOD_COMPARE({_sum(code, p['code'])}, 'month')", None,
                "данные есть за несколько периодов — видно, растём или падаем",
                [p["code"]])

    # 4. Итоги — только по основному разрезу: сумму месячного или недельного
    # столбца виджет считает и без метрики, а список от них разрастается втрое.
    for p in facts:
        if not _is_main_slice(p["slice"]):
            continue
        add("total_sum", f"{p['subject']}: всего",
            _sum(code, p["code"]), None,
            "итог по столбцу — основа для остальных расчётов", [p["code"]])

    return specs


async def suggest_from_data(conn, org_id, dataset_code: Optional[str] = None,
                            object_id: Optional[str] = None) -> dict:
    datasets = await _datasets(conn, org_id, dataset_code, object_id)
    existing = await _existing_formulas(conn, org_id)
    existing_codes = {r["code"] for r in await conn.fetch(
        "select code from metrics where organization_id=$1", org_id)}

    specs: List[dict] = []
    for ds in datasets:
        fields = await _numeric_fields(conn, org_id, ds["code"])
        if not fields:
            continue
        for spec in _build_specs(ds, fields):
            if _norm_formula(spec["formula"]) in existing:
                continue  # такая метрика уже заведена — не предлагаем повторно
            existing.add(_norm_formula(spec["formula"]))
            specs.append(spec)
            if len(specs) >= MAX_SUGGESTIONS:
                break
        if len(specs) >= MAX_SUGGESTIONS:
            break

    _assign_codes(specs, existing_codes)
    return {"specs": specs, "datasets": [{"code": d["code"], "name": d["name"], "periods": d["periods"]}
                                         for d in datasets]}
