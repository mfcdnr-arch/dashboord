"""«Сообщить о проблеме» прямо с виджета (п. 15 списка заказчика — обратная
связь пользователь → администратор).

Механизм обращений в системе есть с волны C, но добраться до него человек мог
только через «Кабинет», и там его встречало пустое поле. Дальше начиналось
самое дорогое: объяснить словами, ГДЕ проблема. «На дашборде с обращениями
цифра какая-то не такая» — по такому описанию администратор не найдёт ни
отчёт, ни показатель, и переписка уходит на два круга уточнений.

Поэтому контекст собирает СЕРВЕР, а не клиент:

  • названия дашборда, страницы и виджета берутся из БД по его id;
  • что это за цифра — тем же `explain_widgets`, что рисует подсказку ⓘ, а не
    отдельным текстом: иначе объяснение в обращении однажды разошлось бы с
    объяснением на экране, и спорить пришлось бы уже о них;
  • **снимок значения** считается тем же `compute_widget_data`, что рисует сам
    виджет, — администратор видит ровно то число, на которое смотрел человек.

Отдельно про сбой расчёта: если виджет не считается, это не повод отказать в
жалобе — наоборот, текст ошибки уезжает в обращение. Часто это и есть ответ на
вопрос «почему у меня пусто», полученный до того, как администратор открыл
отчёт.

**Второй системы обращений не заводим.** Жалоба создаётся тем же
`appeals.create_appeal`, что и обращение из кабинета: тот же тред, те же
уведомления, та же запись в аудите. Разница только в том, что первое сообщение
уже содержит ответ на вопрос «где».

**Повторная жалоба на тот же виджет** дописывается в незакрытое обращение, а не
заводит второе: человек, у которого «опять не то число», жмёт кнопку столько
раз, сколько раз посмотрел, — очередь администратора не должна забиваться
дублями одной беды.

Видимость соблюдается через ту же `visible_dashboard_ids`: пожаловаться можно
только на то, что тебе показывают. Иначе кнопка стала бы способом узнать
названия чужих отчётов и показателей.
"""
from __future__ import annotations

import json
from typing import Optional

from ._base import DashboardError
from ._explain import explain_widgets, widget_configs
from ._rls import visible_dashboard_ids

# Вид проблемы: человек выбирает одним нажатием, а не формулирует. Список
# короткий сознательно — длинный опросник читают хуже, чем пишут текстом.
KINDS = {
    "wrong_value": "Неверная цифра",
    "no_data": "Нет данных",
    "unclear": "Непонятно, что показывает",
    "broken": "Виджет не открывается / ошибка",
    "other": "Другое",
}

MAX_COMMENT = 2000


def _num(value) -> str:
    """Число по-русски: 929 825 / 37,18. Обращение читает человек, а не машина."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    text = f"{v:,.2f}" if abs(v - round(v)) > 1e-9 else f"{round(v):,d}"
    return text.replace(",", " ").replace(".", ",")


def _ru_date(value) -> str:
    """Дата по-русски. Расчёт виджета отдаёт as_of и объектом date, и строкой
    ISO (через кэш) — «данные на 2026-08-05» в обращении читается как машинный
    вывод, а его читает человек."""
    if hasattr(value, "strftime"):
        return value.strftime("%d.%m.%Y")
    text = str(value)
    try:
        from datetime import date
        return date.fromisoformat(text[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return text


def _snapshot(res: dict) -> str:
    """Что было на экране в момент жалобы — одной строкой."""
    unit = f" {res['unit']}" if res.get("unit") else ""
    parts = []
    if res.get("type") in ("kpi", "gauge") and res.get("value") is not None:
        parts.append(f"на экране: {_num(res['value'])}{unit}")
    elif res.get("type") == "plan_fact":
        pct = f", выполнение {_num(res['pct'])} %" if res.get("pct") is not None else ""
        parts.append(f"на экране: план {_num(res.get('plan'))}, факт {_num(res.get('fact'))}{pct}")
    elif res.get("categories"):
        parts.append(f"на экране: {len(res['categories'])} строк(и) данных")
    elif res.get("rows"):
        parts.append(f"на экране: {len(res['rows'])} строк(и) таблицы")
    if res.get("as_of"):
        parts.append(f"данные на {_ru_date(res['as_of'])}")
    if res.get("period_locked"):
        # Половина жалоб «цифра не обновилась» относится именно к срезам.
        parts.append("📌 закреплённый срез — не обновляется")
    return " · ".join(parts)


async def _context(conn, org_id, user: dict, widget_id: str) -> dict:
    w = await conn.fetchrow(
        "select w.id, w.name, w.widget_type, w.config, w.dashboard_id, w.page_id, "
        "       d.name as dashboard_name, p.name as page_title "
        "from widgets w "
        "join dashboards d on d.id = w.dashboard_id "
        "left join dashboard_pages p on p.id = w.page_id "
        "where w.id=$1::uuid and w.organization_id=$2", widget_id, org_id)
    if w is None:
        raise DashboardError("Виджет не найден")
    visible = await visible_dashboard_ids(conn, org_id, user)
    if str(w["dashboard_id"]) not in visible:
        raise DashboardError("Виджет не найден")
    return dict(w)


async def _figure_text(conn, org_id, w: dict) -> str:
    """Что это за цифра — тем же текстом, что и подсказка ⓘ на экране."""
    try:
        cfg = w["config"]
        if isinstance(cfg, str):
            cfg = json.loads(cfg)
        rows = [{"id": w["id"], "widget_type": w["widget_type"], "config": cfg}]
        explained = await explain_widgets(conn, org_id, widget_configs(rows))
        return explained.get(str(w["id"]), "")
    except Exception:  # noqa: BLE001 — пояснение необязательно, жалоба важнее
        return ""


async def _value_text(conn, org_id, user: dict, widget_id: str) -> str:
    """Снимок значения. Сбой расчёта не отменяет жалобу, а становится её частью:
    «виджет не считается» — это и есть диагноз, ради которого человек пришёл."""
    from ._widgetdata import compute_widget_data
    try:
        # NB: user — ТОЛЬКО именованным. Позиционно он уходит в from_date, и
        # расчёт молча падает на проверке доступа (уже наступали 17.08).
        res = await compute_widget_data(conn, org_id, widget_id, user=user)
    except Exception as e:  # noqa: BLE001
        return f"⚠ виджет не считается: {e}"
    return _snapshot(res) if isinstance(res, dict) else ""


def _compose(kind: str, comment: str, w: dict, figure: str, value: str) -> str:
    lines = [comment.strip() or f"{KINDS[kind]} (без описания)", "", "—— где это ——",
             f"Дашборд: «{w['dashboard_name']}»"
             + (f", страница «{w['page_title']}»" if w.get("page_title") else ""),
             f"Виджет: «{w['name']}»",
             f"Что не так: {KINDS[kind]}"]
    if figure:
        lines.append(f"Показатель: {figure}")
    if value:
        lines.append(f"Значение: {value}")
    return "\n".join(lines)


async def report_widget_problem(conn, org_id, user: dict, widget_id: str,
                                kind: str, comment: Optional[str]) -> dict:
    if kind not in KINDS:
        raise DashboardError("Неизвестный вид проблемы")
    comment = (comment or "").strip()[:MAX_COMMENT]

    w = await _context(conn, org_id, user, widget_id)
    figure = await _figure_text(conn, org_id, w)
    value = await _value_text(conn, org_id, user, widget_id)
    body = _compose(kind, comment, w, figure, value)

    from ..appeals import service as appeals_svc

    # Повтор по тому же виджету — в уже открытый тред. Ищем только СВОИ
    # незакрытые обращения: жалоба коллеги на тот же виджет — отдельный разговор.
    existing = await conn.fetchval(
        "select id from appeals where organization_id=$1 and user_id=$2 "
        "and status <> 'closed' and context->>'widget_id' = $3 "
        "order by updated_at desc limit 1", org_id, user["id"], str(w["id"]))
    if existing is not None:
        await appeals_svc.add_message(conn, org_id, user, str(existing), body)
        return {"appeal_id": str(existing), "appended": True,
                "subject": None, "widget_name": w["name"]}

    subject = f"{KINDS[kind]}: «{w['name']}» на дашборде «{w['dashboard_name']}»"
    created = await appeals_svc.create_appeal(conn, org_id, user, subject, body)
    await conn.execute(
        "update appeals set context=$2::jsonb where id=$1::uuid",
        created["id"],
        json.dumps({
            "kind": kind,
            "widget_id": str(w["id"]), "widget_name": w["name"],
            "dashboard_id": str(w["dashboard_id"]), "dashboard_name": w["dashboard_name"],
            "page_id": str(w["page_id"]) if w.get("page_id") else None,
            "page_title": w.get("page_title"),
        }, ensure_ascii=False))
    return {"appeal_id": created["id"], "appended": False,
            "subject": subject, "widget_name": w["name"]}
