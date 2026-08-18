"""Сводный дашборд «План/факт» — по ВСЕМ объектам и папкам сразу.

Отличие от полосы «план-факт» в дашборде объекта: та отвечает за одну форму из
одной папки и остаётся как была. Здесь собирается общая картина выполнения
планов по всей организации — то, что открывают, чтобы одним взглядом понять,
где отставание.

**Пары «План + Факт» ищутся тем же правилом, что и в мастере сборки**
(`_plan_fact_pairs`): по разбору названий граф госформы «Показатель · Роль ·
Разрез». План берётся в любом разрезе (он и так задан накопительно, «до
1 сентября»), а факт — только в ОСНОВНОМ: сравнивать накопительный план с
недельным срезом заведомо неверно. Правило одно на всю систему, иначе сводная
страница противоречила бы дашборду объекта.

**Факт всегда за последнюю дату.** Отдельного механизма для этого не нужно:
виджет читает последний неотменённый выпуск набора данных, поэтому новый отчёт
той же формы подхватывается сам. Дата, за которую показаны цифры, подписана
под виджетом («🕓 данные на …») и считается при каждом открытии.
"""
from __future__ import annotations

from typing import Optional

from ._base import DashboardError
from ._suggest import WIDGET_SIZE, _plan_fact_pairs, collect_object_datasets

PAGE_PLAN_FACT = "План/факт"

# Шкала выполнения плана: <50 % красный, 50–70 оранжевый, 70–85 жёлтый,
# от 85 % зелёный. Правила проверяются сверху вниз, срабатывает первое — поэтому
# порядок здесь значим и менять его нельзя.
#
# Перевыполнение (>100 %) остаётся ЗЕЛЁНЫМ по решению заказчика: это не
# проблема, а точное значение всё равно подписано числом рядом с полосой.
PLAN_FACT_SCALE = [
    {"level": "danger", "op": "lt", "value": 50, "label": "ниже 50 % плана"},
    {"level": "poor", "op": "lt", "value": 70, "label": "50–70 % плана"},
    {"level": "warn", "op": "lt", "value": 85, "label": "70–85 % плана"},
    {"level": "good", "op": "gte", "value": 85, "label": "85 % и выше"},
]

PF_W, PF_H = WIDGET_SIZE["plan_fact"]
PER_ROW = 12 // PF_W


async def collect_plan_fact(conn, org_id) -> list:
    """Все пары «План + Факт» организации: по каждому объекту и его наборам.

    Возвращает список словарей с объектом, набором и парой полей — из него
    строятся и предпросмотр («что будет собрано»), и сами виджеты. Одна
    функция на оба случая намеренно: иначе обещанное число виджетов однажды
    разошлось бы с результатом.
    """
    objects = await conn.fetch(
        "select id, name from objects where organization_id=$1 order by name", org_id)
    out: list = []
    for obj in objects:
        datasets = await collect_object_datasets(conn, org_id, str(obj["id"]))
        for ds in datasets:
            for plan, fact in _plan_fact_pairs(ds["fields"]):
                out.append({
                    "object_id": str(obj["id"]), "object_name": obj["name"],
                    "dataset_code": ds["code"], "dataset_name": ds["name"],
                    "plan": plan, "fact": fact,
                })
    return out


def _widget_name(item: dict, many_objects: bool) -> str:
    """Имя виджета: показатель, а при нескольких объектах — с объектом впереди.

    Название объекта добавляем ТОЛЬКО когда объектов больше одного: у одного
    подразделения повторённый на каждом виджете префикс съедает строку, и от
    самого показателя остаётся многоточие.
    """
    from ..metrics.data_suggestions import _split_name
    subject = _split_name(item["fact"]["name"]).get("subject") or item["fact"]["name"]
    return f"{item['object_name']}: {subject}" if many_objects else subject


def plan_fact_specs(items: list) -> list:
    """Спецификации виджетов сводной страницы — по паре на показатель."""
    many = len({i["object_id"] for i in items}) > 1
    specs = []
    for i, item in enumerate(items):
        specs.append({
            "name": _widget_name(item, many),
            "widget_type": "plan_fact",
            "config": {
                "dataset_code": item["dataset_code"],
                "plan_field": item["plan"]["code"],
                "fact_field": item["fact"]["code"],
                "alerts": [dict(r) for r in PLAN_FACT_SCALE],
                "alert_on": "pct",
            },
            "position_x": (i % PER_ROW) * PF_W,
            "position_y": (i // PER_ROW) * PF_H,
            "width": PF_W, "height": PF_H,
        })
    return specs


async def plan_fact_plan(conn, org_id) -> dict:
    """Предпросмотр: что попадёт на сводную страницу и из каких папок."""
    items = await collect_plan_fact(conn, org_id)
    by_object: dict = {}
    for it in items:
        by_object.setdefault(it["object_name"], []).append(
            _widget_name(it, False))
    return {
        "widgets": len(items),
        "objects": [{"name": k, "indicators": v} for k, v in by_object.items()],
    }


async def build_plan_fact_dashboard(conn, org_id, user_id, name: Optional[str] = None,
                                    dashboard_id: Optional[str] = None,
                                    force: bool = False) -> dict:
    """Собрать (или пересобрать) сводный дашборд «План/факт».

    Пересборка заменяет наполнение, но НЕ сам дашборд: на нём висят права
    доступа, обсуждение и история — тот же принцип, что в мастере сборки.
    """
    items = await collect_plan_fact(conn, org_id)
    if not items:
        # Пустой дашборд собирать нельзя: человек решит, что система сломалась.
        # Говорим настоящую причину — в формах нет граф с ролью «План».
        raise DashboardError(
            "Не нашлось ни одной пары «План + Факт». Такая пара собирается из двух граф "
            "одной формы: одна с ролью «План», вторая — «Факт» в основном разрезе. "
            "Проверьте, что в загруженных формах есть графы плана.")

    specs = plan_fact_specs(items)
    from . import service as svc  # ленивый импорт: избегаем цикла модулей

    if dashboard_id:
        d = await conn.fetchval(
            "select id from dashboards where id=$1::uuid and organization_id=$2",
            dashboard_id, org_id)
        if d is None:
            raise DashboardError("Дашборд не найден")
        did = str(d)
        await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
        await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
    else:
        dash = await svc.create_dashboard(
            conn, org_id, user_id, name or "План/факт",
            "Сводная страница выполнения планов по всем папкам. Факт — за последний отчёт "
            "каждой формы; цвет полосы: до 50 % красный, 50–70 оранжевый, 70–85 жёлтый, "
            "от 85 % зелёный.", None, force=force)
        did = str(dash["id"])

    page = await svc.create_page(conn, org_id, user_id, did, PAGE_PLAN_FACT, None)
    pid = str(page["id"])
    for spec in specs:
        await svc.create_widget(
            conn, org_id, user_id, pid, spec["name"], spec["widget_type"], spec["config"],
            {"position_x": spec["position_x"], "position_y": spec["position_y"],
             "width": spec["width"], "height": spec["height"]})
    return {"dashboard_id": did, "page_id": pid, "widgets": len(specs),
            "objects": len({i["object_id"] for i in items})}
