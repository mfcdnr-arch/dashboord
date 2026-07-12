"""Точка входа Dashboard API (FastAPI).

Модульная архитектура: каждый домен — отдельный пакет в app/modules/<name>/
со своим router. Здесь только сборка приложения и подключение роутеров.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import db
from .config import settings
from .modules.auth.bootstrap import ensure_seed
from .modules.auth.router import router as auth_router
from .modules.documents.router import router as documents_router
from .modules.documents.storage import ensure_bucket
from .modules.objects.router import router as objects_router
from .modules.system.router import router as system_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    await ensure_seed()
    ensure_bucket()
    yield
    await db.disconnect()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# Роутеры модулей. По мере разработки сюда добавляются:
# auth, access, objects, ingestion, metrics, dashboards, moderation,
# viewer, archive, reports, admin, notifications, audit.
app.include_router(system_router)
app.include_router(auth_router)
app.include_router(objects_router)
app.include_router(documents_router)


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
