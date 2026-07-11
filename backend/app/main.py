"""Точка входа Dashbord API (FastAPI).

Модульная архитектура: каждый домен — отдельный пакет в app/modules/<name>/
со своим router. Здесь только сборка приложения и подключение роутеров.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import db
from .config import settings
from .modules.system.router import router as system_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    yield
    await db.disconnect()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# Роутеры модулей. По мере разработки сюда добавляются:
# auth, access, objects, ingestion, metrics, dashboards, moderation,
# viewer, archive, reports, admin, notifications, audit.
app.include_router(system_router)


@app.get("/health", tags=["system"])
async def health():
    db_ok = False
    try:
        db_ok = await db.check_db()
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "service": settings.app_name,
        "env": settings.app_env,
        "db": "ok" if db_ok else "unavailable",
    }


@app.get("/", tags=["system"])
async def root():
    return {"service": settings.app_name, "docs": "/docs"}
