"""Предложения виджетов и авто-сборка дашборда (вынесено из service.py).

Правила, не ИИ: по числовым полям датасета собираются готовые спецификации
виджетов; уже построенное для этого датасета из предложений вычитается.
Функции реэкспортируются из service.py — внешние вызовы не меняются.
"""
from __future__ import annotations

from typing import List

from ..metrics import resolver as mr
from ._alerts import _cfg
from ._base import DashboardError

# Потолок карточек в авто-сборке на один датасет. Показываем ВСЕ показатели
# формы (у госформ их бывает полтора десятка), но у файла на сотню граф
# столько виджетов сделали бы страницу нечитаемой, а её открытие — медленным:
# каждая карточка считается отдельно. Остальные графы видны в таблице ниже.
MAX_AUTO_KPI = 24


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


async def auto_build(conn, org_id, user_id, object_id: str, name=None) -> dict:
    """Собирает черновик дашборда по объекту: на каждый датасет объекта — KPI,
    столбчатый график, динамику (если >1 периода) и таблицу-первичку."""
    obj = await conn.fetchrow(
        "select id, name from objects where id=$1::uuid and organization_id=$2", object_id, org_id)
    if obj is None:
        raise DashboardError("Объект не найден")
    ds = await conn.fetch(
        "select code, max(name) as name, count(distinct reporting_period_start) as periods "
        "from dataset_releases where organization_id=$1 and object_id=$2::uuid and status<>'superseded' "
        "group by code order by max(created_at) desc", org_id, object_id)
    if not ds:
        raise DashboardError("У объекта нет выпущенных датасетов — сначала распознайте документ")

    from . import service as svc  # ленивый импорт: избегаем цикла модулей
    dash = await svc.create_dashboard(conn, org_id, user_id, name or f"Дашборд «{obj['name']}»",
                                  f"Авто-сборка по объекту «{obj['name']}»", None)
    did = str(dash["id"])
    page = await svc.create_page(conn, org_id, user_id, did, "Обзор", None)
    pid = str(page["id"])

    n, y = 0, 0
    for d in ds:
        code, dsname = d["code"], (d["name"] or d["code"])
        fields = await _dataset_numeric_fields(conn, org_id, code)
        if not fields:
            continue
        # Карточка на КАЖДЫЙ числовой показатель, по 4 в ряд (сетка 12 колонок).
        # Раньше брались только первые два поля — на форме из 14 граф человек
        # видел в предпросмотре разметки 14 карточек, а на собранном дашборде
        # две, и это выглядело как потеря данных.
        f0 = fields[0]
        has_dyn = (d["periods"] or 0) > 1
        # В имени карточки — ТОЛЬКО показатель. Префикс с именем датасета,
        # повторённый на десятке карточек, съедал строку целиком, и от самого
        # показателя оставалось многоточие. Датасет виден по значку ⓘ и по
        # графику с таблицей ниже — они подписаны полностью.
        shown = fields[:MAX_AUTO_KPI]
        for i, f in enumerate(shown):
            await svc.create_widget(conn, org_id, user_id, pid, f["name"], "kpi",
                                {"dataset_code": code, "value_field": f["code"]},
                                {"position_x": (i % 4) * 3, "position_y": y + (i // 4) * 3,
                                 "width": 3, "height": 3}); n += 1
        y += ((len(shown) + 3) // 4) * 3

        # Ряд графиков: столбцы + динамика заполняют 12 колонок целиком, иначе
        # страница вытягивается вниз при пустом месте справа. Без динамики
        # (один период в серии) график забирает освободившиеся колонки.
        chart_w = 8 if has_dyn else 12
        await svc.create_widget(conn, org_id, user_id, pid, f"{dsname}: {f0['name']} по строкам", "bar",
                            {"dataset_code": code, "value_field": f0["code"]},
                            {"position_x": 0, "position_y": y, "width": chart_w, "height": 6}); n += 1
        if has_dyn:
            await svc.create_widget(conn, org_id, user_id, pid, f"{dsname}: динамика {f0['name']}", "dynamics",
                                {"dataset_code": code, "value_field": f0["code"]},
                                {"position_x": 8, "position_y": y, "width": 4, "height": 6}); n += 1
        # Сравнение всех показателей одним графиком: десяток карточек даёт точные
        # числа, но не даёт увидеть соотношение между ними. Высота растёт с числом
        # показателей — на 13 столбиков стандартных 6 рядов мало: шапка и пояснение
        # под графиком съедают карточку, и на сам график остаётся полоска.
        if len(shown) > 1:
            # 8 рядов — замерено: при 6 график ужимается до полоски (легенда,
            # пояснение про шкалу и подпись источника съедают карточку), при
            # 10 внизу остаётся пустое место — график выше базовой высоты не растёт.
            cmp_h = 8 if len(shown) > 4 else 6
            await svc.create_widget(conn, org_id, user_id, pid, f"{dsname}: сравнение показателей", "compare",
                                {"dataset_code": code, "value_fields": [f["code"] for f in shown]},
                                {"position_x": 0, "position_y": y + 6, "width": 12, "height": cmp_h}); n += 1
            y += cmp_h
        await svc.create_widget(conn, org_id, user_id, pid, f"{dsname}: таблица", "table",
                            {"dataset_code": code},
                            {"position_x": 0, "position_y": y + 6, "width": 12, "height": 6}); n += 1
        y += 12
    return {"dashboard_id": did, "page_id": pid, "widgets": n}
