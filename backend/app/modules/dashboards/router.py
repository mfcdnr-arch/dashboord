"""Модуль «Дашборды» (HTTP): агрегатор под-роутеров по группам маршрутов.

Дашборды/страницы/виджеты создают admin/moderator; чтение — любой авторизованный.
Сами маршруты — в _router_dashboards (CRUD/шаблоны/публикация/страницы),
_router_access (гранты/row-RLS/комментарии/пресеты), _router_widgets
(виджеты/данные/drill), _router_archive (архив дашбордов).
"""
from __future__ import annotations

from fastapi import APIRouter

from ._router_access import router as _access_router
from ._router_archive import router as _archive_router
from ._router_dashboards import router as _dashboards_router
from ._router_widgets import router as _widgets_router

router = APIRouter(tags=["dashboards"])
router.include_router(_dashboards_router)
router.include_router(_access_router)
router.include_router(_widgets_router)
router.include_router(_archive_router)
