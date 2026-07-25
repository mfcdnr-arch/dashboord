"""Точка входа Dashboard API (FastAPI).

Модульная архитектура: каждый домен — отдельный пакет в app/modules/<name>/
со своим router. Здесь только сборка приложения и подключение роутеров.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import cache, db
from .config import settings
from .modules.auth.bootstrap import ensure_seed
from .modules.audit.router import router as audit_router
from .modules.auth.router import router as auth_router
from .modules.catalog.router import router as catalog_router
from .modules.dashboards.router import router as dashboards_router
from .modules.documents.router import router as documents_router
from .modules.home.router import router as home_router
from .modules.documents.storage import ensure_bucket
from .modules.ingestion import queue as ingestion_queue
from .modules.ingestion.router import router as ingestion_router
from .modules.maintenance.router import router as maintenance_router
from .modules.metrics.router import router as metrics_router
from .modules.moderation.router import router as moderation_router
from .modules.notifications.router import router as notifications_router
from .modules.objects.router import router as objects_router
from .modules.reports.router import router as reports_router
from .modules.system.router import router as system_router
from .modules.users.router import router as users_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    await ensure_seed()
    ensure_bucket()
    await ingestion_queue.connect()
    await cache.connect()
    yield
    await cache.disconnect()
    await ingestion_queue.disconnect()
    await db.disconnect()


app = FastAPI(title=settings.app_name, lifespan=lifespan)


class ClientIPMiddleware:
    """Кладёт IP запроса в contextvar db.current_ip на время обработки.

    Чистый ASGI-middleware (не BaseHTTPMiddleware) — выполняется в том же
    контексте, что и эндпоинт, поэтому contextvar видна в acquire().
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        fwd = headers.get(b"x-forwarded-for")
        if fwd:
            ip = fwd.decode(errors="ignore").split(",")[0].strip() or None
        else:
            client = scope.get("client")
            ip = client[0] if client else None
        token = db.current_ip.set(ip)
        try:
            await self.app(scope, receive, send)
        finally:
            db.current_ip.reset(token)


app.add_middleware(ClientIPMiddleware)

# Роутеры модулей. По мере разработки сюда добавляются:
# auth, access, objects, ingestion, metrics, dashboards, moderation,
# viewer, archive, reports, admin, notifications, audit.
app.include_router(system_router)
app.include_router(auth_router)
app.include_router(audit_router)
app.include_router(objects_router)
app.include_router(documents_router)
app.include_router(ingestion_router)
app.include_router(metrics_router)
app.include_router(dashboards_router)
app.include_router(moderation_router)
app.include_router(home_router)
app.include_router(users_router)
app.include_router(reports_router)
app.include_router(catalog_router)
app.include_router(notifications_router)
app.include_router(maintenance_router)


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
