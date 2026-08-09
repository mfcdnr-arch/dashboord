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
    """Датасеты организации с родословной: объект → папка → документ.

    Когда объектов несколько, по одному коду датасета не понять, к какому файлу
    относится предложение, — поэтому тянем и название объекта, и папку с
    документом, из которых датасет выпущен.
    """
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
        "count(distinct r.reporting_period_start) as periods, "
        "max(o.name) as object_name, max(f.name) as folder_name, max(d.original_filename) as document_name "
        "from dataset_releases r "
        "left join objects o on o.id = r.object_id "
        "left join document_versions dv on dv.id = r.source_document_version_id "
        "left join documents d on d.id = dv.document_id "
        "left join folders f on f.id = d.folder_id "
        f"where {' and '.join(where)} group by r.code order by max(o.name), max(r.name)",
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


async def _field_values(conn, org_id, code: str) -> Dict[str, Dict[tuple, float]]:
    """Значения по столбцам: {код столбца: {(период, строка): число}}.

    Нужны для поиска связок, которых нет в словаре: словарь знает только те пары
    слов, что я в него вписал, а данные говорят сами за себя.
    """
    rows = await conn.fetch(
        "select dv.canonical_field_code as code, r.reporting_period_start as period, "
        "       coalesce(dv.row_label,'') as row_label, dv.value_number as v "
        "from dataset_values dv join dataset_releases r on r.id = dv.dataset_release_id "
        "where r.organization_id=$1 and r.code=$2 and r.status<>'superseded' and dv.value_number is not null",
        org_id, code)
    out: Dict[str, Dict[tuple, float]] = {}
    for r in rows:
        out.setdefault(r["code"], {})[(r["period"], r["row_label"])] = float(r["v"])
    return out


# Насколько уверенно пара выглядит как «часть от целого».
_MIN_POINTS = 3      # меньше — совпадение может быть случайным
_MAX_RATIO = 0.98    # часть почти равна целому — скорее два одинаковых столбца
_MIN_RATIO = 0.001   # доля в тысячные доли процента — вероятно, разные величины


def _detect_part_of_whole(values: Dict[str, Dict[tuple, float]], parsed: List[dict]) -> List[tuple]:
    """Пары столбцов, которые ПО ДАННЫМ ведут себя как «часть → целое».

    Признак: в каждой общей точке (период + строка) одно значение не превосходит
    другое, отношение держится в разумных пределах и таких точек достаточно.
    Это находит связки, которых нет в словаре, — без правки кода и без выдумок:
    вывод делается из чисел, а не из похожести слов.

    Возвращает [(часть, целое, средняя доля в %)].
    """
    by_code = {p["code"]: p for p in parsed}
    found: List[tuple] = []
    codes = [p["code"] for p in parsed if p["code"] in values]

    for a in codes:
        for b in codes:
            if a == b:
                continue
            pa, pb = by_code[a], by_code[b]
            # Сравниваем только сопоставимые столбцы: один разрез, ни один не план.
            if pa["role"] == "plan" or pb["role"] == "plan":
                continue
            if _clean(pa["slice"]).lower() != _clean(pb["slice"]).lower():
                continue
            common = set(values[a]) & set(values[b])
            if len(common) < _MIN_POINTS:
                continue
            ratios = []
            ok = True
            for key in common:
                part, whole = values[a][key], values[b][key]
                if whole <= 0 or part < 0 or part > whole:
                    ok = False
                    break
                ratios.append(part / whole)
            if not ok or not ratios:
                continue
            avg = sum(ratios) / len(ratios)
            if not (_MIN_RATIO <= avg <= _MAX_RATIO):
                continue
            found.append((a, b, avg * 100.0))
    return found


async def _verify(conn, org_id, formula: str) -> dict:
    """Проверка предложения расчётом: разбирается ли формула и считается ли она.

    Требование заказчика — «любое добавление не должно ломать работоспособность».
    Поэтому новое правило не может протащить в интерфейс формулу, которая упадёт:
    сначала она вычисляется на реальных данных, и только потом показывается.
    Импорт локальный — service тянет resolver и БД, на уровне модуля это дало бы
    круговой импорт.
    """
    from .service import MetricError, preview
    try:
        res = await preview(conn, org_id, formula)
    except (MetricError, Exception):  # noqa: B014 — любая ошибка = предложение не показываем
        return {"ok": False, "value": None}
    v = res.get("value")
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        return {"ok": False, "value": None}
    return {"ok": True, "value": float(v)}


async def _existing_formulas(conn, org_id) -> set:
    rows = await conn.fetch(
        "select v.formula_expression from metric_versions v "
        "join metrics m on m.id = v.metric_id where m.organization_id=$1", org_id)
    return {_norm_formula(r["formula_expression"]) for r in rows}


def _sum(ds: str, field: str) -> str:
    return f"SUM(field('{ds}','{field}'))"


def _build_specs(ds: dict, fields: List[dict],
                 values: Optional[Dict[str, Dict[tuple, float]]] = None) -> List[dict]:
    """Правила разбора: что осмысленно посчитать по этому набору столбцов.

    values (значения по столбцам) необязательны: без них работают словарные
    правила, с ними дополнительно ищутся связки, которых в словаре нет.
    """
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

    # 4. Связки, которых НЕТ в словаре, — найденные по самим числам.
    # Словарь знает только те пары слов, что в него вписаны; данные говорят сами
    # за себя: если один столбец во всех точках вложен в другой, это часть целого.
    if values:
        known = {(s["based_on"][0], s["based_on"][1]) for s in specs if s["type"] == "percent_of" and len(s["based_on"]) == 2}
        known |= {(b, a) for a, b in known}
        for part, whole, avg in _detect_part_of_whole(values, parsed):
            if (whole, part) in known or (part, whole) in known:
                continue  # уже предложено словарным правилом
            pp, pw = by_code_of(parsed, part), by_code_of(parsed, whole)
            slice_hint = f" ({pp['slice']})" if pp["slice"] else ""
            add("percent_of_auto", f"{pp['subject']} — доля от «{pw['subject']}»{slice_hint}, %",
                f"PERCENT_OF({_sum(code, whole)}, {_sum(code, part)})", "%",
                f"найдено по данным: значения одного столбца всегда укладываются в другой "
                f"(в среднем {avg:.1f} %) — похоже на часть от целого",
                [whole, part])

    # 5. Итоги — только по основному разрезу: сумму месячного или недельного
    # столбца виджет считает и без метрики, а список от них разрастается втрое.
    for p in facts:
        if not _is_main_slice(p["slice"]):
            continue
        add("total_sum", f"{p['subject']}: всего",
            _sum(code, p["code"]), None,
            "итог по столбцу — основа для остальных расчётов", [p["code"]])

    return specs


def by_code_of(parsed: List[dict], code: str) -> dict:
    return next(p for p in parsed if p["code"] == code)


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
        values = await _field_values(conn, org_id, ds["code"])
        for spec in _build_specs(ds, fields, values):
            if _norm_formula(spec["formula"]) in existing:
                continue  # такая метрика уже заведена — не предлагаем повторно
            # САМОПРОВЕРКА: предложение показывается, только если оно реально
            # считается на этих данных. Новые правила (в том числе найденные по
            # числам) не могут выдать формулу, которая упадёт у пользователя.
            checked = await _verify(conn, org_id, spec["formula"])
            if not checked["ok"]:
                continue
            spec["preview_value"] = checked["value"]
            existing.add(_norm_formula(spec["formula"]))
            # Родословная у КАЖДОГО предложения: при нескольких объектах иначе не
            # понять, из какого файла взяты столбцы.
            spec["dataset_name"] = ds.get("name")
            spec["object_name"] = ds.get("object_name")
            spec["folder_name"] = ds.get("folder_name")
            spec["document_name"] = ds.get("document_name")
            specs.append(spec)
            if len(specs) >= MAX_SUGGESTIONS:
                break
        if len(specs) >= MAX_SUGGESTIONS:
            break

    _assign_codes(specs, existing_codes)
    return {
        "specs": specs,
        "datasets": [{"code": d["code"], "name": d["name"], "periods": d["periods"],
                      "object_name": d.get("object_name"), "folder_name": d.get("folder_name"),
                      "document_name": d.get("document_name")} for d in datasets],
    }
