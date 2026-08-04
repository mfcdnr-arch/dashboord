"""Общие зависимости HTTP-роутеров модуля «Дашборды» (вынесено из router.py)."""
from __future__ import annotations

from fastapi import HTTPException, status

from ..auth.deps import require_roles
from .service import DashboardError

manage = require_roles("admin", "moderator")
admin_only = require_roles("admin", "superadmin")


def _bad(e: DashboardError) -> HTTPException:
    msg = str(e)
    code = status.HTTP_404_NOT_FOUND if "не найден" in msg else status.HTTP_400_BAD_REQUEST
    return HTTPException(code, msg)
