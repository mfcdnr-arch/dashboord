"""Модуль «Главная» (HTTP): сводка витрины + выбор ключевых KPI (admin/moderator)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ... import db
from ..auth.deps import get_current_user, require_roles
from . import service
from .service import HomeError

router = APIRouter(tags=["home"])
manage = require_roles("superadmin", "admin", "moderator")


class KpiIn(BaseModel):
    metric_code: str = Field(min_length=1)


@router.get("/home")
async def home(user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        return await service.get_home(conn, user["organization_id"], user)


@router.get("/home/portal")
async def portal_home(user: dict = Depends(get_current_user)):
    """Главная обычного пользователя: объявления, его отчёты, что нового, инструкции."""
    async with db.get_pool().acquire() as conn:
        return await service.portal_home(conn, user["organization_id"], user)


@router.post("/home/kpis", status_code=status.HTTP_201_CREATED)
async def add_kpi(body: KpiIn, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        try:
            return await service.add_kpi(conn, user["organization_id"], user["id"], body.metric_code)
        except HomeError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.delete("/home/kpis/{metric_code}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_kpi(metric_code: str, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        await service.remove_kpi(conn, user["organization_id"], metric_code)
