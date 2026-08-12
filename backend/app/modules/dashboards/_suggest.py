"""Предложения виджетов и авто-сборка дашборда (вынесено из service.py).

Правила, не ИИ: по числовым полям датасета собираются готовые спецификации
виджетов; уже построенное для этого датасета из предложений вычитается.
Функции реэкспортируются из service.py — внешние вызовы не меняются.
"""
from __future__ import annotations

from typing import List, Optional

from ..metrics import resolver as mr
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
BLOCKS = ["kpi", "compare", "dynamics", "bar", "table"]


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
        out.append({
            "code": d["code"], "name": d["name"] or d["code"],
            "periods": d["periods"] or 0, "releases": d["releases"] or 0,
            "fields": fields,
        })
    return out


def plan_auto_build(datasets: list, selection: Optional[dict] = None) -> list:
    """Что именно будет создано — список виджетов с местом на сетке.

    `selection` = {code: {"fields": [коды], "blocks": [виды]}}. Не передан —
    берём всё: мастер по умолчанию предлагает полный набор.
    """
    specs: list = []
    y = 0
    for d in datasets:
        code, dsname = d["code"], d["name"]
        sel = (selection or {}).get(code)
        if selection is not None and sel is None:
            continue  # набор данных снят галочкой целиком
        want_fields = set(sel["fields"]) if sel and sel.get("fields") is not None else None
        blocks = set(sel["blocks"]) if sel and sel.get("blocks") is not None else set(BLOCKS)

        fields = [f for f in d["fields"] if want_fields is None or f["code"] in want_fields]
        if not fields:
            continue
        shown = fields[:MAX_AUTO_KPI]
        f0 = shown[0]
        has_dyn = d["periods"] > 1

        # Карточка на КАЖДЫЙ выбранный показатель, по 4 в ряд (сетка 12 колонок).
        # Имя карточки — только показатель: префикс с названием набора данных,
        # повторённый на десятке карточек, съедал строку целиком.
        if "kpi" in blocks:
            for i, f in enumerate(shown):
                specs.append({"name": f["name"], "widget_type": "kpi",
                              "config": {"dataset_code": code, "value_field": f["code"]},
                              "position_x": (i % 4) * 3, "position_y": y + (i // 4) * 3,
                              "width": 3, "height": 3})
            y += ((len(shown) + 3) // 4) * 3

        # Динамика по каждому показателю нужна, когда периодов несколько: карточки
        # и таблица показывают ПОСЛЕДНИЙ выпуск, и без трендов дашборд по полутора
        # десяткам форм выглядит так, будто взята одна дата.
        grid_dyn = has_dyn and "dynamics" in blocks and len(shown) > 1
        if "bar" in blocks:
            # Динамика в этом ряду — только когда показатель ОДИН: иначе тренд
            # первого показателя дублировал бы карточку из сетки ниже.
            solo_dyn = has_dyn and "dynamics" in blocks and not grid_dyn
            specs.append({"name": f"{dsname}: {f0['name']} по строкам", "widget_type": "bar",
                          "config": {"dataset_code": code, "value_field": f0["code"]},
                          "position_x": 0, "position_y": y, "width": 8 if solo_dyn else 12, "height": 6})
            if solo_dyn:
                specs.append({"name": f"{dsname}: динамика {f0['name']}", "widget_type": "dynamics",
                              "config": {"dataset_code": code, "value_field": f0["code"]},
                              "position_x": 8, "position_y": y, "width": 4, "height": 6})
            y += 6

        if grid_dyn:
            grid = shown[:MAX_AUTO_DYNAMICS]
            for i, f in enumerate(grid):
                specs.append({"name": f"Динамика: {f['name']}", "widget_type": "dynamics",
                              "config": {"dataset_code": code, "value_field": f["code"]},
                              "position_x": (i % 3) * 4, "position_y": y + (i // 3) * 6,
                              "width": 4, "height": 6})
            y += ((len(grid) + 2) // 3) * 6

        # Сравнение: десяток карточек даёт точные числа, но не даёт увидеть
        # соотношение. 8 рядов — замерено: при 6 график ужимается до полоски
        # (легенда и пояснение съедают карточку), при 10 внизу пустое место.
        if "compare" in blocks and len(shown) > 1:
            specs.append({"name": f"{dsname}: сравнение показателей", "widget_type": "compare",
                          "config": {"dataset_code": code, "value_fields": [f["code"] for f in shown]},
                          "position_x": 0, "position_y": y, "width": 12,
                          "height": 8 if len(shown) > 4 else 6})
            y += 8 if len(shown) > 4 else 6

        if "table" in blocks:
            specs.append({"name": f"{dsname}: таблица", "widget_type": "table",
                          "config": {"dataset_code": code},
                          "position_x": 0, "position_y": y, "width": 12, "height": 6})
            y += 6
    return specs


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
    return {
        "object": {"id": str(obj["id"]), "name": obj["name"]},
        "datasets": [{k: v for k, v in d.items()} for d in datasets],
        "blocks": BLOCKS,
        "warnings": warnings,
        "widgets": len(specs),
        "by_type": {t: sum(1 for s in specs if s["widget_type"] == t) for t in BLOCKS},
    }


async def auto_build(conn, org_id, user_id, object_id: str, name=None,
                     selection: Optional[dict] = None, dashboard_id: Optional[str] = None) -> dict:
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
    if not specs:
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

    page = await svc.create_page(conn, org_id, user_id, did, "Обзор", None)
    pid = str(page["id"])
    for s in specs:
        await svc.create_widget(
            conn, org_id, user_id, pid, s["name"], s["widget_type"], s["config"],
            {"position_x": s["position_x"], "position_y": s["position_y"],
             "width": s["width"], "height": s["height"]})
    return {"dashboard_id": did, "page_id": pid, "widgets": len(specs)}
