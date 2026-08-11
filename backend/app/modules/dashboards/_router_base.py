"""Общие зависимости HTTP-роутеров модуля «Дашборды» (вынесено из router.py)."""
from __future__ import annotations

from fastapi import HTTPException, status

from ..auth.deps import require_roles
from .service import DashboardError

manage = require_roles("superadmin", "admin", "moderator")
admin_only = require_roles("admin", "superadmin")
# Удаление дашборда — только владелец системы: оно необратимо (в отличие от
# снятия с публикации или архивации), а восстановить дашборд из журнала нельзя.
superadmin_only = require_roles("superadmin")


def _bad(e: DashboardError) -> HTTPException:
    """Доменная ошибка → код ответа.

    Кроме «не найдено» различаем ещё два случая, иначе клиент не отличит
    «нельзя вам» и «нельзя сейчас» от обычной ошибки ввода: нехватку прав (403)
    и отказ по состоянию объекта — например, попытку удалить опубликованный
    дашборд (409).
    """
    msg = str(e)
    if "не найден" in msg:
        code = status.HTTP_404_NOT_FOUND
    elif msg.startswith("Недостаточно прав"):
        code = status.HTTP_403_FORBIDDEN
    elif "удаление отменено" in msg.lower():
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(code, msg)
