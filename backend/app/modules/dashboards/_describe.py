"""Описание дашборда словами — черновик, который пишет система.

Зачем. В списке дашбордов у руководителя есть только имя («Внедрение сервиса
МАХ — еженедельный доклад»), и по нему не понять, что внутри и стоит ли
открывать. Поле описания в схеме было с самого начала, но заполнять его
руками никто не будет: у заказчика оно пустое у всех дашбордов.

Правила, не ИИ: состав читается из самих виджетов — какие показатели выведены,
из какого объекта и папки взяты данные, за какой период и как часто приходят
отчёты. Ровно то, что человек написал бы сам, посмотрев на страницу.

Система НЕ сохраняет текст молча: черновик показывается в окне правки, а
сохраняет его человек. Описание — обещание читателю, и отвечать за него
должен тот, кто его дал.
"""
from __future__ import annotations

from typing import List, Optional

from ._alerts import _cfg

# Сколько показателей перечислять поимённо. Список из пятнадцати имён госформы
# перестаёт быть описанием и становится вторым дашбордом.
MAX_NAMED_FIELDS = 4

_TYPE_RU = {
    "kpi": "карточки показателей", "gauge": "спидометры", "plan_fact": "план и факт",
    "dynamics": "динамика по периодам", "compare": "сравнение показателей",
    "bar": "столбцы", "line": "линия", "pie": "круговая", "table": "таблица",
    "pivot": "сводная таблица", "heatmap": "тепловая карта", "yoy": "год к году",
    "waterfall": "водопад", "cross_dataset_compare": "сравнение источников",
    "text": "пояснения", "image": "изображения",
}


def _ru_date(value) -> str:
    return value.strftime("%d.%m.%Y") if hasattr(value, "strftime") else str(value)


def _plural(n: int, one: str, few: str, many: str) -> str:
    tail = n % 100
    if 11 <= tail <= 14:
        return many
    last = n % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


async def describe_dashboard(conn, org_id, dashboard_id: str) -> dict:
    """Черновик описания + факты, из которых он собран."""
    d = await conn.fetchrow(
        "select d.id, d.name, d.description, o.name as object_name, f.name as folder_name "
        "from dashboards d "
        "left join folders f on f.id = d.folder_id "
        "left join objects o on o.id = f.object_id "
        "where d.id=$1::uuid and d.organization_id=$2", dashboard_id, org_id)
    if d is None:
        return {"draft": "", "current": None}

    widgets = await conn.fetch(
        "select widget_type, name, config from widgets where dashboard_id=$1::uuid", dashboard_id)
    pages = await conn.fetchval(
        "select count(*) from dashboard_pages where dashboard_id=$1::uuid", dashboard_id) or 0

    dataset_codes: List[str] = []
    for w in widgets:
        cfg = _cfg(w)
        for code in [cfg.get("dataset_code")] + [s.get("dataset_code") for s in (cfg.get("series") or [])]:
            if code and code not in dataset_codes:
                dataset_codes.append(code)

    # Показатели называем по КАРТОЧКАМ и спидометрам: именно они отвечают на
    # вопрос «что здесь меряют», а таблица и график по строкам — это разрезы.
    # Имена приводим к короткому виду и дедуплицируем: один показатель в трёх
    # разрезах («нарастающим итогом», «за месяц», «за неделю») — это ОДИН
    # показатель, и трижды повторить его в описании значит ничего не сказать.
    named: List[str] = []
    for w in widgets:
        if w["widget_type"] not in ("kpi", "gauge", "plan_fact"):
            continue
        short = _short(w["name"])
        if short and short not in named:
            named.append(short)

    period = None
    if dataset_codes:
        period = await conn.fetchrow(
            "select min(reporting_period_start) as first, max(reporting_period_start) as last, "
            "  count(distinct reporting_period_start) as periods "
            "from dataset_releases where organization_id=$1 and code = any($2::text[]) "
            "and status <> 'superseded' and reporting_period_start is not null",
            org_id, dataset_codes)

    parts: List[str] = []

    where = " · ".join(x for x in (d["object_name"], d["folder_name"]) if x)
    if where:
        parts.append(f"Данные объекта «{where}».")

    if named:
        shown = ", ".join(named[:MAX_NAMED_FIELDS])
        rest = len(named) - MAX_NAMED_FIELDS
        tail = f" и ещё {rest} {_plural(rest, 'показатель', 'показателя', 'показателей')}" if rest > 0 else ""
        parts.append(f"Показатели: {shown}{tail}.")

    kinds = _kinds(widgets)
    if kinds:
        parts.append(f"На {pages} {_plural(pages, 'странице', 'страницах', 'страницах')}: {kinds}.")

    if period and period["periods"]:
        n = period["periods"]
        if n > 1:
            parts.append(
                f"Отчёты с {_ru_date(period['first'])} по {_ru_date(period['last'])} — "
                f"{n} {_plural(n, 'период', 'периода', 'периодов')}; "
                "цифры обновляются сами, как только выпущен новый отчёт.")
        else:
            parts.append(f"Данные за {_ru_date(period['last'])}.")

    return {
        "draft": " ".join(parts),
        "current": d["description"],
        "facts": {
            "object": d["object_name"], "folder": d["folder_name"],
            "pages": pages, "widgets": len(widgets),
            "metrics_named": named[:MAX_NAMED_FIELDS],
            "datasets": dataset_codes,
            "periods": (period["periods"] if period else 0) or 0,
        },
    }


def _short(name: str) -> str:
    """Имя показателя без служебного хвоста госформы.

    «Количество обращений … · Факт · нарастающим итогом**» в описании читается
    как шум: роль и разрез важны на самом дашборде, а не в аннотации к нему.
    """
    head = name.split("·")[0].strip(" *")
    return head[:60].rstrip() + ("…" if len(head) > 60 else "")


def _kinds(widgets) -> str:
    counts: dict = {}
    for w in widgets:
        label = _TYPE_RU.get(w["widget_type"])
        if label:
            counts[label] = counts.get(label, 0) + 1
    return ", ".join(f"{label} ({n})" for label, n in counts.items())


def featured_summary(row) -> Optional[str]:
    """Что показать в подборке под именем дашборда: описание или ничего."""
    text = (row["description"] or "").strip()
    return text or None
