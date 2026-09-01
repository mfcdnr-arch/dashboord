"""Базовые определения дашбордов (вынесено из service.py): ошибка и типы виджетов.
Лист-модуль без зависимостей — импортируется остальными подмодулями и фасадом."""
from __future__ import annotations

from datetime import date


class DashboardError(Exception):
    """Ошибка бизнес-логики дашбордов (в роутере → 400/404)."""


def ru_date(value) -> str:
    """Дата по-русски (ДД.ММ.ГГГГ) для текста, который читает человек.

    NB: по модулю дашбордов разбросано ещё несколько частных `_ru_date`
    (`_report`, `_describe`, `_suggest`, `_widgetexport`) с чуть разными
    сигнатурами. Новый код берёт эту; сводить старые в одну — отдельная
    правка, она трогает несвязанные модули и здесь была бы лишним риском.
    """
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%d.%m.%Y")
    text = str(value)
    try:
        return date.fromisoformat(text[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return text


WIDGET_TYPES = {"kpi", "gauge", "table", "bar", "line", "pie", "plan_fact", "dynamics", "compare",
                "heatmap", "pivot", "waterfall", "objects_compare", "cross_dataset_compare", "yoy",
                "funnel", "status_grid", "matrix", "kpi_group", "bullet", "thermometer", "ranked", "spark_table",
                "text", "image"}
# Режимы раскладки страницы: свободная сетка (виджеты двигают мышью) и «поток»
# (место и размер считаются по типу виджета при отрисовке — страница не может
# поехать и не оставляет дыр).
LAYOUT_MODES = {"grid", "flow"}

# Аннотационные виджеты (без данных) — заголовок/текст и картинка/лого.
ANNOTATION_TYPES = {"text", "image"}
