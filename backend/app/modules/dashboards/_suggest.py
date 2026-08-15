"""Предложения виджетов и авто-сборка дашборда (вынесено из service.py).

Правила, не ИИ: по числовым полям датасета собираются готовые спецификации
виджетов; уже построенное для этого датасета из предложений вычитается.
Функции реэкспортируются из service.py — внешние вызовы не меняются.
"""
from __future__ import annotations

import json
from typing import List, Optional

from ..metrics import resolver as mr
from ..metrics.data_suggestions import _is_main_slice, _split_name, _subject_key
from ._alerts import _cfg
from ._base import DashboardError

# Потолок карточек в авто-сборке на один датасет. Показываем ВСЕ показатели
# формы (у госформ их бывает полтора десятка), но у файла на сотню граф
# столько виджетов сделали бы страницу нечитаемой, а её открытие — медленным:
# каждая карточка считается отдельно. Остальные графы видны в таблице ниже.
MAX_AUTO_KPI = 24
# Потолок графиков динамики. Тренд — самое ценное, когда форм много, но каждый
# график считается отдельным запросом: на широкой форме страница открывалась бы
# заметно дольше. Остальные показатели добавляются кнопкой «💡 Предложить ещё».
MAX_AUTO_DYNAMICS = 16


# --------------------------------------------------------------------------- #
# Авто-сборка дашборда из объекта (rule-based, не ИИ)
# --------------------------------------------------------------------------- #
async def _dataset_numeric_fields(conn, org_id, dataset_code: str) -> List[dict]:
    rel = await mr._active_release(conn, org_id, dataset_code)
    if rel is None:
        return []
    rows = await conn.fetch(
        "select drf.canonical_field_code as code, coalesce(cf.name, drf.canonical_field_code) as name "
        "from dataset_release_fields drf "
        "left join canonical_fields cf on cf.code=drf.canonical_field_code "
        "  and cf.object_id=(select object_id from dataset_releases where id=$1) "
        "where drf.dataset_release_id=$1 and coalesce(cf.data_type,'text')='number' "
        "order by drf.canonical_field_code", rel)
    return [dict(r) for r in rows]


def _spec_signature(widget_type: str, cfg: dict):
    """Ключ дедупликации предложения: тип + датасет + набор полей (без учёта
    порядка/названия виджета) — «то же самое», даже если названо иначе."""
    if widget_type == "plan_fact":
        fields = tuple(sorted(x for x in (cfg.get("plan_field"), cfg.get("fact_field")) if x))
    elif cfg.get("value_fields"):
        fields = tuple(sorted(cfg["value_fields"]))
    elif cfg.get("value_field"):
        fields = (cfg["value_field"],)
    else:
        fields = ()
    return (widget_type, cfg.get("dataset_code"), fields)


async def _existing_widget_signatures(conn, org_id, dataset_code: str) -> set:
    """Волна «рекомендации»: сигнатуры УЖЕ построенных виджетов по этому
    датасету — ОРГАНИЗАЦИОННО-широкий поиск (не только текущий дашборд), т.к.
    dataset_code однозначно принадлежит одному объекту — так предложения не
    повторяют то, что уже собрано где угодно для этого же объекта/датасета."""
    rows = await conn.fetch(
        "select widget_type, config from widgets where organization_id=$1 and config->>'dataset_code'=$2",
        org_id, dataset_code)
    return {_spec_signature(r["widget_type"], _cfg(r)) for r in rows}


async def suggest_widgets(conn, org_id, dataset_code: str) -> dict:
    """Подсказки «что собрать» под датасет: готовые спецификации виджетов
    (KPI по каждому числовому полю, график по строкам, динамика при >1 периода,
    сравнение/план-факт при ≥2 полях, таблица-первичка). Пользователь выбирает.
    Delta-aware (рекомендательная система, 2026-08-04): то, что уже построено
    для этого датасета — где угодно в организации — из предложений убирается,
    чтобы не предлагать заново то же самое."""
    fields = await _dataset_numeric_fields(conn, org_id, dataset_code)
    if not fields:
        raise DashboardError("У датасета нет числовых полей — сначала распознайте документ")
    dsname = await conn.fetchval(
        "select max(name) from dataset_releases where organization_id=$1 and code=$2 and status<>'superseded'",
        org_id, dataset_code) or dataset_code
    periods = await conn.fetchval(
        "select count(distinct reporting_period_start) from dataset_releases "
        "where organization_id=$1 and code=$2 and status<>'superseded'", org_id, dataset_code) or 0

    specs: List[dict] = []
    for f in fields:
        specs.append({"name": f"Σ {f['name']}", "widget_type": "kpi",
                      "config": {"dataset_code": dataset_code, "value_field": f["code"]}, "width": 3, "height": 3})
    f0 = fields[0]
    specs.append({"name": f"{f0['name']} по строкам", "widget_type": "bar",
                  "config": {"dataset_code": dataset_code, "value_field": f0["code"]}, "width": 5, "height": 6})
    specs.append({"name": f"Водопад: {f0['name']}", "widget_type": "waterfall",
                  "config": {"dataset_code": dataset_code, "value_field": f0["code"]}, "width": 6, "height": 6})
    if periods > 1:
        specs.append({"name": f"Динамика: {f0['name']}", "widget_type": "dynamics",
                      "config": {"dataset_code": dataset_code, "value_field": f0["code"]}, "width": 6, "height": 6})
    if len(fields) >= 2:
        specs.append({"name": "Сравнение полей", "widget_type": "compare",
                      "config": {"dataset_code": dataset_code, "value_fields": [f["code"] for f in fields[:4]], "viz": "bar"},
                      "width": 6, "height": 7})
        specs.append({"name": "Тепловая карта", "widget_type": "heatmap",
                      "config": {"dataset_code": dataset_code, "value_fields": [f["code"] for f in fields[:6]]},
                      "width": 6, "height": 7})
        specs.append({"name": "Сводная таблица", "widget_type": "pivot",
                      "config": {"dataset_code": dataset_code, "value_fields": [f["code"] for f in fields[:6]]},
                      "width": 6, "height": 6})
        specs.append({"name": f"План/факт: {fields[0]['name']} / {fields[1]['name']}", "widget_type": "plan_fact",
                      "config": {"dataset_code": dataset_code, "plan_field": fields[0]["code"], "fact_field": fields[1]["code"]},
                      "width": 4, "height": 5})
    specs.append({"name": f"{dsname}: таблица", "widget_type": "table",
                  "config": {"dataset_code": dataset_code}, "width": 6, "height": 6})

    existing = await _existing_widget_signatures(conn, org_id, dataset_code)
    delta = [s for s in specs if _spec_signature(s["widget_type"], s["config"]) not in existing]
    return {"specs": delta, "total_candidates": len(specs), "already_built": len(specs) - len(delta)}


# --------------------------------------------------------------------------- #
# Авто-сборка: сбор данных → план раскладки → создание
#
# Раскладка считается ОДНОЙ функцией `plan_auto_build`, а предпросмотр и
# создание лишь по-разному ей пользуются. Иначе «будет создано N виджетов»
# рано или поздно разошлось бы с тем, что получилось на самом деле, — та же
# ловушка, из-за которой предпросмотр разметки считают тем же кодом, что и
# выпуск датасета.
# --------------------------------------------------------------------------- #
# Общие блоки дашборда. «kpi» и «dynamics» остались для совместимости выбора,
# но вид конкретного показателя задаётся отдельно (VIEWS) — так человек может
# сказать «этот числом, этот трендом», а не только «все или никак».
BLOCKS = ["plan_fact", "kpi", "compare", "dynamics", "bar", "table"]


async def collect_object_datasets(conn, org_id, object_id: str) -> list:
    """Наборы данных объекта с их показателями — основа и плана, и мастера."""
    rows = await conn.fetch(
        "select code, max(name) as name, count(distinct reporting_period_start) as periods, "
        "  count(*) as releases "
        "from dataset_releases where organization_id=$1 and object_id=$2::uuid and status<>'superseded' "
        "group by code order by max(created_at) desc", org_id, object_id)
    out = []
    for d in rows:
        fields = await _dataset_numeric_fields(conn, org_id, d["code"])
        # Сами отчётные даты нужны мастеру: по ним человек выбирает недели,
        # для которых нужны отдельные страницы (этап 3).
        dates = await conn.fetch(
            "select distinct reporting_period_start as p from dataset_releases "
            "where organization_id=$1 and code=$2 and status<>'superseded' "
            "and reporting_period_start is not null order by 1 desc limit 60",
            org_id, d["code"])
        out.append({
            "code": d["code"], "name": d["name"] or d["code"],
            "periods": d["periods"] or 0, "releases": d["releases"] or 0,
            "fields": fields,
            "period_dates": [r["p"].isoformat() for r in dates],
        })
    return out


# Вид показателя на дашборде. Раньше все получали одинаковую карточку; теперь
# вид подбирается по РОЛИ показателя, которую система и так разбирает в имени
# столбца госформы («Показатель · Роль · Разрез»).
VIEWS = ["kpi", "dynamics", "both", "none"]
PAGE_OVERVIEW, PAGE_DYNAMICS, PAGE_RAW = "Обзор", "Динамика", "Первичные данные"
PAGE_PERIOD_PREFIX = "Отчёт за"
# Потолок страниц-срезов: каждая страница — это ещё десяток запросов данных,
# а дашборд из полусотни вкладок невозможно листать.
MAX_AUTO_PERIOD_PAGES = 8


def default_view(field_name: str, has_periods: bool) -> str:
    """Как показать показатель, если человек не выбрал сам.

    Недельное значение само по себе мало что говорит — его смотрят в движении,
    поэтому «за отчётную неделю» получает и число, и тренд. Накопительный итог
    смотрят числом. Без нескольких периодов тренда быть не может.
    """
    if not has_periods:
        return "kpi"
    parsed = _split_name(field_name)
    slc = (parsed.get("slice") or "").lower()
    if "недел" in slc:
        return "both"
    return "kpi"


def _plan_fact_pairs(fields: list) -> list:
    """Пары «План + Факт» одного показателя в основном разрезе.

    Две карточки рядом заставляют считать процент в уме, а виджет «План-факт»
    показывает полосу выполнения сразу. Пары ищем только в ОСНОВНОМ разрезе:
    план в форме задан накопительный («до 1 сентября»), и сравнивать его с
    недельным фактом было бы заведомо неверно.
    """
    # План берём в ЛЮБОМ разрезе: он и так задан накопительно («до 1 сентября»),
    # а его собственная подпись под «нарастающим итогом» не подходит. Требование
    # основного разреза относится к ФАКТУ — иначе план сравнивался бы с недельным
    # или месячным срезом, что заведомо неверно. Правило то же, что в подборе
    # метрик (metrics/data_suggestions), чтобы система не противоречила себе.
    plans: dict = {}
    for f in fields:
        p = _split_name(f["name"])
        if p.get("role") == "plan":
            plans[_subject_key(p.get("subject", ""))] = f
    out = []
    for f in fields:
        p = _split_name(f["name"])
        if p.get("role") != "fact" or not _is_main_slice(p.get("slice", "")):
            continue
        plan = plans.get(_subject_key(p.get("subject", "")))
        if plan:
            out.append((plan, f))
    return out


def plan_auto_build(datasets: list, selection: Optional[dict] = None) -> list:
    """Что именно будет создано — список виджетов с местом на сетке и страницей.

    `selection` = {code: {"fields": [коды], "blocks": [виды], "views": {код: вид}}}.
    Не передан — берём всё с автоматически подобранными видами.

    Страницы разделены по смыслу: «Обзор» отвечает на «как сейчас», «Динамика» —
    на «как менялось», «Первичные данные» — «откуда цифры». Одна длинная страница
    со всем сразу читалась плохо, да и данные грузятся постранично.
    """
    specs: list = []
    ov_y = dyn_y = raw_y = 0
    for d in datasets:
        code, dsname = d["code"], d["name"]
        sel = (selection or {}).get(code)
        if selection is not None and sel is None:
            continue  # набор данных снят галочкой целиком
        want_fields = set(sel["fields"]) if sel and sel.get("fields") is not None else None
        blocks = set(sel["blocks"]) if sel and sel.get("blocks") is not None else set(BLOCKS)
        views = (sel or {}).get("views") or {}

        fields = [f for f in d["fields"] if want_fields is None or f["code"] in want_fields]
        if not fields:
            continue
        shown = fields[:MAX_AUTO_KPI]
        has_dyn = d["periods"] > 1

        # views/has_dyn связываем явно: замыкание на переменную цикла — классическая
        # ловушка (в следующей итерации функция увидела бы уже другой набор данных).
        def view_of(f, views=views, has_dyn=has_dyn):
            v = views.get(f["code"]) or default_view(f["name"], has_dyn)
            return v if v in VIEWS else "kpi"

        # ── Обзор: план-факт полосой, остальные — карточками, снизу сравнение ──
        if "plan_fact" in blocks:
            pairs = _plan_fact_pairs(shown)
            for i, (plan, fact) in enumerate(pairs):
                specs.append({"page": PAGE_OVERVIEW,
                              "name": f"{_split_name(fact['name'])['subject']}: план и факт",
                              "widget_type": "plan_fact",
                              "config": {"dataset_code": code,
                                         "plan_field": plan["code"], "fact_field": fact["code"]},
                              "position_x": (i % 2) * 6, "position_y": ov_y + (i // 2) * 5,
                              "width": 6, "height": 5})
            if pairs:
                # По 2 в ряд: пара «план-факт» шире карточки (в ней два числа,
                # разница и полоса), а 2×6 заполняют 12 колонок ровно — иначе
                # карточки затекали бы в остаток ряда сбоку от полос.
                ov_y += ((len(pairs) + 1) // 2) * 5

        cards = [f for f in shown if view_of(f) in ("kpi", "both")] if "kpi" in blocks else []
        for i, f in enumerate(cards):
            specs.append({"page": PAGE_OVERVIEW, "name": f["name"], "widget_type": "kpi",
                          "config": {"dataset_code": code, "value_field": f["code"]},
                          "position_x": (i % 4) * 3, "position_y": ov_y + (i // 4) * 3,
                          "width": 3, "height": 3})
        if cards:
            ov_y += ((len(cards) + 3) // 4) * 3

        # Сравнение: десяток карточек даёт точные числа, но не даёт увидеть
        # соотношение. 8 рядов — замерено: при 6 график ужимается до полоски.
        if "compare" in blocks and len(cards) > 1:
            specs.append({"page": PAGE_OVERVIEW, "name": f"{dsname}: сравнение показателей",
                          "widget_type": "compare",
                          "config": {"dataset_code": code, "value_fields": [f["code"] for f in cards]},
                          "position_x": 0, "position_y": ov_y, "width": 12,
                          "height": 8 if len(cards) > 4 else 6})
            ov_y += 8 if len(cards) > 4 else 6

        # ── Динамика: тренд по каждому показателю, которому он назначен ──
        trends = ([f for f in shown if view_of(f) in ("dynamics", "both")][:MAX_AUTO_DYNAMICS]
                  if has_dyn and "dynamics" in blocks else [])
        for i, f in enumerate(trends):
            specs.append({"page": PAGE_DYNAMICS, "name": f"Динамика: {f['name']}",
                          "widget_type": "dynamics",
                          "config": {"dataset_code": code, "value_field": f["code"]},
                          "position_x": (i % 3) * 4, "position_y": dyn_y + (i // 3) * 6,
                          "width": 4, "height": 6})
        if trends:
            dyn_y += ((len(trends) + 2) // 3) * 6

        # ── Первичные данные: разрез по строкам и сама таблица ──
        if "bar" in blocks:
            specs.append({"page": PAGE_RAW, "name": f"{dsname}: {shown[0]['name']} по строкам",
                          "widget_type": "bar",
                          "config": {"dataset_code": code, "value_field": shown[0]["code"]},
                          "position_x": 0, "position_y": raw_y, "width": 12, "height": 6})
            raw_y += 6
        if "table" in blocks:
            specs.append({"page": PAGE_RAW, "name": f"{dsname}: таблица", "widget_type": "table",
                          "config": {"dataset_code": code},
                          "position_x": 0, "position_y": raw_y, "width": 12, "height": 6})
            raw_y += 6

        # ── Страницы по отчётным периодам ────────────────────────────────────
        # Сводные страницы обновляются сами: виджет читает последний выпуск.
        # Страница периода — наоборот, СРЕЗ: у её виджетов закреплена дата, и
        # приход новой недели их не меняет. Оба режима нужны заказчику, и
        # разницу между ними человек должен понимать (о ней сказано на самой
        # странице и в мастере).
        for period in _selected_periods(sel, d):
            py = 0
            page = f"{PAGE_PERIOD_PREFIX} {_ru_date(period)}"
            for i, f in enumerate(shown[:MAX_AUTO_KPI]):
                specs.append({"page": page, "name": f["name"], "widget_type": "kpi",
                              "config": {"dataset_code": code, "value_field": f["code"],
                                         "period": period},
                              "position_x": (i % 4) * 3, "position_y": py + (i // 4) * 3,
                              "width": 3, "height": 3})
            py += ((len(shown[:MAX_AUTO_KPI]) + 3) // 4) * 3
            specs.append({"page": page, "name": f"{dsname}: таблица за {_ru_date(period)}",
                          "widget_type": "table",
                          "config": {"dataset_code": code, "period": period},
                          "position_x": 0, "position_y": py, "width": 12, "height": 6})
    return specs


def _ru_date(iso: str) -> str:
    """Отчётная дата в подписи страницы — по-русски: ДД.ММ.ГГГГ."""
    parts = str(iso).split("-")
    return ".".join(reversed(parts)) if len(parts) == 3 else str(iso)


def _selected_periods(sel: Optional[dict], dataset: dict) -> list:
    """Отчётные даты, для которых человек попросил отдельные страницы.

    Пусто по умолчанию: страницы по неделям создаются ТОЛЬКО по явному выбору.
    У заказчика 15 недель — молча собрать 15 страниц значило бы сделать
    дашборд, который невозможно открыть.
    """
    if not sel:
        return []
    wanted = sel.get("periods") or []
    known = set(dataset.get("period_dates") or [])
    return [p for p in wanted if p in known][:MAX_AUTO_PERIOD_PAGES]


async def auto_build_plan(conn, org_id, object_id: str, selection: Optional[dict] = None) -> dict:
    """Предпросмотр мастера: что нашли в объекте и что будет создано."""
    obj = await conn.fetchrow(
        "select id, name from objects where id=$1::uuid and organization_id=$2", object_id, org_id)
    if obj is None:
        raise DashboardError("Объект не найден")
    datasets = await collect_object_datasets(conn, org_id, object_id)
    if not datasets:
        raise DashboardError("У объекта нет выпущенных датасетов — сначала распознайте документ")

    warnings = []
    if len(datasets) > 1:
        warnings.append(
            "В объекте несколько наборов данных: "
            + ", ".join(f"«{d['code']}»" for d in datasets)
            + ". Обычно у объекта один набор, а разные коды появляются, когда выпуск "
              "сделали под новым именем — тогда недельные формы не складываются в один ряд.")
    trimmed = [d for d in datasets if len(d["fields"]) > MAX_AUTO_KPI]
    if trimmed:
        warnings.append(
            f"Показателей больше {MAX_AUTO_KPI} — на дашборд попадут первые {MAX_AUTO_KPI}, "
            "остальные видны в таблице.")

    specs = plan_auto_build(datasets, selection)

    # Расчётные показатели («% выполнения плана», «доля доставленных»…): их
    # находит разбор имён столбцов — тот же, что в разделе «Метрики». Здесь они
    # нужны, чтобы человек мог поставить галочку прямо при сборке, а не заводить
    # метрику отдельно и потом руками добавлять по ней виджет.
    metrics = await _metric_options(conn, org_id, object_id)

    page_names = [PAGE_OVERVIEW, PAGE_DYNAMICS, PAGE_RAW] + sorted(
        {s["page"] for s in specs if str(s.get("page", "")).startswith(PAGE_PERIOD_PREFIX)})
    return {
        "object": {"id": str(obj["id"]), "name": obj["name"]},
        "metrics": metrics,
        "saved_selection": await _saved_selection(conn, object_id),
        "datasets": [{k: v for k, v in d.items()} for d in datasets],
        "blocks": BLOCKS,
        "warnings": warnings,
        "widgets": len(specs),
        "pages": [
            {"name": t, "widgets": sum(1 for s in specs if (s.get("page") or PAGE_OVERVIEW) == t)}
            for t in page_names
            if any((s.get("page") or PAGE_OVERVIEW) == t for s in specs)
        ],
        "by_type": {t: sum(1 for s in specs if s["widget_type"] == t) for t in BLOCKS},
        # Как система предлагает показать каждый показатель — мастер выводит это
        # рядом с ним и даёт поменять.
        "views": {
            d["code"]: {f["code"]: default_view(f["name"], d["periods"] > 1) for f in d["fields"]}
            for d in datasets
        },
    }


async def _metric_options(conn, org_id, object_id: str) -> list:
    """Расчётные показатели, которые можно завести по данным этого объекта.

    Разбор имён столбцов живёт в `metrics/data_suggestions` и уже используется
    разделом «Метрики» — берём его же, чтобы система не предлагала в двух местах
    разное. Каждое предложение там проверено расчётом на реальных данных, то
    есть заведомо считается.

    Сбой не должен ронять мастер: без расчётных показателей он просто соберёт
    дашборд по сырым графам, как раньше.
    """
    try:
        from ..metrics.data_suggestions import suggest_from_data
        res = await suggest_from_data(conn, org_id, object_id=str(object_id))
    except Exception:  # noqa: BLE001 — подсказка не важнее самой сборки
        return []
    return [
        {"code": s["code"], "name": s["name"], "formula": s["formula"], "unit": s.get("unit"),
         "why": s.get("why"), "preview_value": s.get("preview_value"),
         "dataset_code": s.get("dataset_code")}
        for s in res.get("specs", [])
    ]


async def _saved_selection(conn, object_id: str) -> Optional[dict]:
    """Выбор прошлой сборки — им мастер открывается в следующий раз."""
    raw = await conn.fetchval("select build_preferences from objects where id=$1::uuid", object_id)
    if not raw:
        return None
    return json.loads(raw) if isinstance(raw, str) else raw


async def _remember_selection(conn, object_id: str, selection: Optional[dict],
                              metrics: Optional[list]) -> None:
    """Запомнить выбор: мастер не должен каждую неделю спрашивать одно и то же."""
    if selection is None and not metrics:
        return
    payload = {"selection": selection or {}, "metrics": list(metrics or [])}
    await conn.execute(
        "update objects set build_preferences=$2::jsonb where id=$1::uuid",
        object_id, json.dumps(payload, ensure_ascii=False, default=str))


async def _create_metric_widgets(conn, org_id, user_id, object_id: str, codes: list,
                                 page_id: str, start_y: int) -> int:
    """Завести выбранные расчётные показатели и поставить по ним карточки.

    Метрика создаётся ЧЕРНОВИКОМ и проходит обычный путь проверки; виджет при
    этом работает сразу, потому что берёт лучшую доступную версию формулы
    (одобренная → проверенная → черновик). Так человек видит число сразу, а
    порядок согласования не нарушается.
    """
    if not codes:
        return 0
    from ..metrics import service as msvc

    options = {m["code"]: m for m in await _metric_options(conn, org_id, object_id)}
    made = 0
    for code in codes:
        spec = options.get(code)
        if spec is None:
            continue  # предложение устарело (метрику уже завели) — молча пропускаем
        try:
            metric = await msvc.create_metric(
                conn, org_id, user_id, spec["code"], spec["name"], spec.get("why"), None)
            await msvc.create_version(
                conn, org_id, user_id, str(metric["id"]), spec["formula"],
                spec.get("unit"), None, "formula")
        except Exception:  # noqa: BLE001 — метрика с таким кодом уже есть
            pass
        from . import service as svc
        await svc.create_widget(
            conn, org_id, user_id, page_id, spec["name"], "kpi",
            {"metric_code": spec["code"], "unit": spec.get("unit")},
            {"position_x": (made % 4) * 3, "position_y": start_y + (made // 4) * 3,
             "width": 3, "height": 3})
        made += 1
    return made


async def auto_build(conn, org_id, user_id, object_id: str, name=None,
                     selection: Optional[dict] = None, dashboard_id: Optional[str] = None,
                     metrics: Optional[list] = None) -> dict:
    """Создаёт (или пересобирает) дашборд по объекту.

    `dashboard_id` — пересобрать существующий: страницы и виджеты заменяются,
    сам дашборд с его правами, комментариями и историей остаётся. Без него
    создаётся новый. Раньше каждое нажатие плодило новый дашборд.
    """
    obj = await conn.fetchrow(
        "select id, name from objects where id=$1::uuid and organization_id=$2", object_id, org_id)
    if obj is None:
        raise DashboardError("Объект не найден")
    datasets = await collect_object_datasets(conn, org_id, object_id)
    if not datasets:
        raise DashboardError("У объекта нет выпущенных датасетов — сначала распознайте документ")
    specs = plan_auto_build(datasets, selection)
    if not specs and not metrics:
        raise DashboardError("Нечего собирать — не выбрано ни одного показателя")

    from . import service as svc  # ленивый импорт: избегаем цикла модулей
    if dashboard_id:
        d = await conn.fetchrow(
            "select id, name from dashboards where id=$1::uuid and organization_id=$2",
            dashboard_id, org_id)
        if d is None:
            raise DashboardError("Дашборд не найден")
        did = str(d["id"])
        # Старое наполнение убираем: пересборка должна дать ровно то, что в плане,
        # а не смесь нового со старым. Сам дашборд не трогаем — на нём висят
        # права доступа, обсуждение и история версий.
        await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
        await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
    else:
        dash = await svc.create_dashboard(conn, org_id, user_id, name or f"Дашборд «{obj['name']}»",
                                          f"Авто-сборка по объекту «{obj['name']}»", None)
        did = str(dash["id"])
        # Папку проставляем сами: мастер и так знает объект, а раньше человек
        # шёл в дашборд и назначал её отдельным действием — иначе дашборд
        # висел «без папки» и не находился фильтром по банку отделов.
        folder_id = await conn.fetchval(
            "select d.folder_id from dataset_releases r "
            "join document_versions dv on dv.id = r.source_document_version_id "
            "join documents d on d.id = dv.document_id "
            "where r.object_id=$1::uuid and r.status <> 'superseded' and d.folder_id is not null "
            "group by d.folder_id order by count(*) desc limit 1", object_id)
        if folder_id:
            await conn.execute("update dashboards set folder_id=$2 where id=$1::uuid", did, folder_id)

    # Страницы создаём в осмысленном порядке и только те, на которых что-то есть:
    # пустая вкладка «Динамика» у формы с одним периодом сбивала бы с толку.
    pages: dict = {}
    first_pid = None
    for spec in specs:
        title = spec.get("page") or PAGE_OVERVIEW
        if title not in pages:
            page = await svc.create_page(conn, org_id, user_id, did, title, None)
            pages[title] = str(page["id"])
            if first_pid is None:
                first_pid = pages[title]
        await svc.create_widget(
            conn, org_id, user_id, pages[title], spec["name"], spec["widget_type"], spec["config"],
            {"position_x": spec["position_x"], "position_y": spec["position_y"],
             "width": spec["width"], "height": spec["height"]})

    # Расчётные показатели: заводим выбранные метрики и ставим по ним карточки
    # на «Обзор» — раньше принятие предложения создавало только черновик, а
    # виджет по нему человек добавлял руками и часто про это забывал.
    made_metrics = 0
    if metrics:
        if PAGE_OVERVIEW not in pages:
            page = await svc.create_page(conn, org_id, user_id, did, PAGE_OVERVIEW, None)
            pages[PAGE_OVERVIEW] = str(page["id"])
            if first_pid is None:
                first_pid = pages[PAGE_OVERVIEW]
        # Ниже всего, что уже разложено на «Обзоре», — иначе карточки наложились бы.
        below = max(
            [s["position_y"] + s["height"] for s in specs
             if (s.get("page") or PAGE_OVERVIEW) == PAGE_OVERVIEW] or [0])
        made_metrics = await _create_metric_widgets(
            conn, org_id, user_id, object_id, metrics, pages[PAGE_OVERVIEW], below)

    await _remember_selection(conn, object_id, selection, metrics)
    return {"dashboard_id": did, "page_id": first_pid, "pages": len(pages),
            "widgets": len(specs) + made_metrics, "metrics": made_metrics}


async def place_metric_widget(conn, org_id, user_id, *, page_id: str, metric_code: str,
                              name: str, unit: Optional[str] = None,
                              based_on: Optional[List[str]] = None,
                              dataset_code: Optional[str] = None) -> dict:
    """Поставить карточку показателя РЯДОМ с близким по смыслу виджетом.

    Новый виджет, добавленный «в конец страницы», уезжает вниз и теряется:
    руководитель смотрит на «Обзор» и не видит, что доля посчитана рядом с тем
    показателем, от которого она берётся. Поэтому ищем виджет, который уже
    показывает поля, лежащие в основе формулы, и встаём вплотную к нему —
    справа, если в ряду есть место, иначе следующей строкой под ним.

    Место выбирает система, но последнее слово за человеком: виджеты можно
    двигать мышью, и перестановка ничего не ломает.
    """
    from . import service as svc

    fields = set(based_on or [])
    # Если поля не переданы, достаём их из САМОЙ формулы показателя: для
    # размещения важно, из чего он считается, а человек этого знать не обязан.
    if not fields:
        derived = await _metric_fields(conn, org_id, metric_code)
        fields = set(derived["fields"])
        dataset_code = dataset_code or (derived["datasets"][0] if derived["datasets"] else None)
    rows = await conn.fetch(
        "select id, config, position_x, position_y, width, height "
        "from widgets where page_id=$1::uuid order by position_y, position_x", page_id)

    best: Optional[dict] = None
    best_score = 0.0
    for r in rows:
        cfg = _cfg(r)
        used = {cfg.get(k) for k in ("value_field", "plan_field", "fact_field") if cfg.get(k)}
        used |= set(cfg.get("value_fields") or [])
        hit = len(used & fields)
        # Родство считаем ДОЛЕЙ совпадения, а не числом совпавших полей.
        # Иначе общий график «Сравнение показателей», перечисляющий все графы
        # формы, всегда выигрывал у карточки нужного показателя — и новая
        # карточка уезжала под него в самый низ страницы, вместо того чтобы
        # встать рядом с показателем, от которого она считается.
        score = (hit / len(used)) if used and hit else 0.0
        # Тот же датасет — слабое родство: лучше, чем ничего, но заведомо
        # уступает совпадению по конкретным показателям.
        if not score and dataset_code and cfg.get("dataset_code") == dataset_code:
            score = 0.1
        if score > best_score:
            best, best_score = r, score

    width, height = 3, 3

    def free(x: int, y: int) -> bool:
        """Свободна ли клетка: иначе сетка растолкает соседей при отрисовке."""
        if x + width > 12:
            return False
        for r in rows:
            rx, ry, rw, rh = r["position_x"], r["position_y"], r["width"], r["height"]
            if x < rx + rw and rx < x + width and y < ry + rh and ry < y + height:
                return False
        return True

    if best is None:
        # Родственника нет — в конец страницы (сетка сама подожмёт вверх).
        pos = {"position_x": 0, "position_y": 999, "width": width, "height": height}
    else:
        bx, by, bw = best["position_x"], best["position_y"], best["width"]
        # Ищем ближайшее СВОБОДНОЕ место: сначала справа от родственника, затем
        # свободные клетки его ряда, затем строка под ним. Ставить в занятую
        # клетку нельзя — сетка при отрисовке сдвинет чужие карточки, и человек
        # увидит, что дашборд «поехал» сам по себе.
        spot = None
        # Сначала вплотную справа, затем свободные места ряда, затем ряды ниже —
        # чем дальше, тем хуже, поэтому спускаемся недалеко (4 ряда карточек).
        for dy in range(0, 4 * height, height):
            y = by + dy
            order = ([bx + bw] if dy == 0 else [bx]) + [c * 3 for c in range(4)]
            for x in order:
                if free(x, y):
                    spot = (x, y)
                    break
            if spot:
                break
        if spot:
            pos = {"position_x": spot[0], "position_y": spot[1], "width": width, "height": height}
        else:
            # Свободного места поблизости нет: ставим ВПЛОТНУЮ справа от
            # родственника и позволяем сетке подвинуть остальных. Соседство
            # важнее неподвижности: карточка, уехавшая в конец страницы, теряет
            # весь смысл «рядом с показателем, из которого считается».
            pos = {"position_x": min(bx + bw, 9), "position_y": by,
                   "width": width, "height": height}

    cfg = {"metric_code": metric_code}
    if unit:
        cfg["unit"] = unit
    w = await svc.create_widget(conn, org_id, user_id, page_id, name, "kpi", cfg, pos)
    return {"widget_id": w["id"], "placed_near": str(best["id"]) if best is not None else None,
            "position": pos}


async def _metric_fields(conn, org_id, metric_code: str) -> dict:
    """Поля и датасеты, на которых стоит формула показателя.

    Берём лучшую версию (одобренная → проверенная → черновик) — ту же, по
    которой виджет и будет считать. Разбираем разобранный AST, а не текст:
    в тексте те же ссылки пришлось бы искать регулярками.
    """
    ast = await conn.fetchval(
        "select mv.formula_ast from metric_versions mv join metrics m on m.id = mv.metric_id "
        "where m.organization_id=$1 and m.code=$2 "
        "order by case mv.status when 'approved' then 0 when 'validated' then 1 "
        "                        when 'draft' then 2 else 3 end, mv.version_no desc limit 1",
        org_id, metric_code)
    if not ast:
        return {"fields": [], "datasets": []}
    if isinstance(ast, str):
        ast = json.loads(ast)

    fields: List[str] = []
    datasets: List[str] = []

    def walk(node) -> None:
        if not isinstance(node, dict):
            return
        if node.get("t") in ("field", "cell"):
            if node.get("field") and node["field"] not in fields:
                fields.append(node["field"])
            if node.get("col") and node["col"] not in fields:
                fields.append(node["col"])
            if node.get("dataset") and node["dataset"] not in datasets:
                datasets.append(node["dataset"])
        for val in node.values():
            if isinstance(val, dict):
                walk(val)
            elif isinstance(val, list):
                for it in val:
                    walk(it)

    walk(ast)
    return {"fields": fields, "datasets": datasets}


async def dashboard_metric_codes(conn, dashboard_id: str) -> list:
    """Коды показателей, уже показанных на дашборде: не предлагаем их дважды."""
    rows = await conn.fetch(
        "select config from widgets where dashboard_id=$1::uuid", dashboard_id)
    out: set = set()
    for r in rows:
        cfg = _cfg(r)
        for key in ("metric_code", "plan_metric", "fact_metric"):
            if cfg.get(key):
                out.add(cfg[key])
    return sorted(out)
