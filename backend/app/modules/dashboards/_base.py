"""Базовые определения дашбордов (вынесено из service.py): ошибка и типы виджетов.
Лист-модуль без зависимостей — импортируется остальными подмодулями и фасадом."""
from __future__ import annotations


class DashboardError(Exception):
    """Ошибка бизнес-логики дашбордов (в роутере → 400/404)."""


WIDGET_TYPES = {"kpi", "gauge", "table", "bar", "line", "pie", "plan_fact", "dynamics", "compare",
                "heatmap", "pivot", "waterfall", "objects_compare", "cross_dataset_compare", "yoy",
                "text", "image"}
# Аннотационные виджеты (без данных) — заголовок/текст и картинка/лого.
ANNOTATION_TYPES = {"text", "image"}
