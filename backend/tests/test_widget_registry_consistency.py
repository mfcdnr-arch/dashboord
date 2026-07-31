"""Согласованность реестра типов виджетов backend↔frontend (фаза 3, урезанный
минимум): дублирование списка типов между `_base.py:WIDGET_TYPES` (backend,
источник валидации) и `WidgetPicker.tsx` (frontend, UI-галерея) — реальное,
но полноценный общий реестр не убирает необходимость писать код рендеринга и
расчёта под каждый тип (см. project_priority_max_automation.md, фаза 3).
Вместо этого — тест, который ловит расхождение сразу при добавлении/переименовании
типа в одном месте и забытом другом, не дожидаясь бага в проде."""
import re
from pathlib import Path

from app.modules.dashboards._base import WIDGET_TYPES

FRONTEND_FILE = Path(__file__).resolve().parents[2] / "frontend/src/components/dashboards/WidgetPicker.tsx"


def _frontend_types() -> set[str]:
    src = FRONTEND_FILE.read_text(encoding="utf-8")
    return set(re.findall(r"\{\s*v:\s*'([a-z_]+)'", src))


def _frontend_icon_keys() -> set[str]:
    src = FRONTEND_FILE.read_text(encoding="utf-8")
    return set(re.findall(r"^\s*([a-z_]+):\s*<svg", src, re.MULTILINE))


def test_widget_picker_gallery_covers_all_backend_widget_types():
    frontend_types = _frontend_types()
    assert frontend_types, "не нашли ни одного типа в WidgetPicker.tsx — сломался regex или файл переехал?"
    missing_in_frontend = WIDGET_TYPES - frontend_types
    extra_in_frontend = frontend_types - WIDGET_TYPES
    assert not missing_in_frontend, (
        f"Есть в backend WIDGET_TYPES, но нет карточки в WidgetPicker.tsx (WIDGET_GROUPS): {missing_in_frontend}")
    assert not extra_in_frontend, (
        f"Есть карточка в WidgetPicker.tsx, но нет в backend WIDGET_TYPES (_base.py): {extra_in_frontend}")


def test_widget_picker_icons_cover_all_backend_widget_types():
    icon_keys = _frontend_icon_keys()
    missing_icons = WIDGET_TYPES - icon_keys
    assert not missing_icons, f"Нет иконки (ICONS) в WidgetPicker.tsx для типов: {missing_icons}"
