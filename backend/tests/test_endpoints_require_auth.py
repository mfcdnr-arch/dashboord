"""Сквозная проверка: КАЖДЫЙ эндпоинт API требует авторизации.

Регрессия финального аудита: `GET /system/info` отвечал без токена и раскрывал
устройство схемы (число таблиц, наличие функции разрешения доступа). Тест
обходит весь список маршрутов из OpenAPI, поэтому новый публичный эндпоинт
нельзя добавить незаметно — его придётся либо закрыть, либо осознанно внести
в список PUBLIC ниже.
"""
import uuid

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

# Осознанно публичные маршруты:
#   /health   — проверка живости для docker healthcheck и smoke;
#   /         — корень (тот же health-ответ);
#   /auth/login, /auth/password-policy — нужны ДО получения токена;
#   /auth/blocked-appeal — обращение заблокированного (JWT получить не может).
PUBLIC = {
    "/health",
    "/",
    "/auth/login",
    "/auth/password-policy",
    "/auth/blocked-appeal",
}

# Коды, означающие «без токена дальше не пустили»:
#   401 — нет/неверный токен; 403 — не хватает прав;
#   422 — тело/параметры не прошли валидацию (данные не выданы);
#   405 — метод не поддерживается на этом пути.
OK_STATUSES = {401, 403, 405, 422}

_FAKE = str(uuid.uuid4())


def _fill(path: str) -> str:
    out = path
    for name in ("dashboard_id", "page_id", "widget_id", "user_id", "metric_id", "version_id",
                 "job_id", "table_id", "folder_id", "object_id", "release_id", "appeal_id",
                 "showcase_id", "item_id", "archive_id", "event_id", "department_id", "grant_id",
                 "template_id", "recipient_id", "preset_id", "comment_id", "doc_id", "service_id",
                 "target_user_id"):
        out = out.replace("{" + name + "}", _FAKE)
    return out.replace("{version_no}", "1").replace("{metric_code}", "test")


async def test_every_endpoint_requires_auth(client):
    from app.main import app

    spec = app.openapi()
    leaks = []
    checked = 0
    for path, ops in spec["paths"].items():
        if path in PUBLIC:
            continue
        url = _fill(path)
        for method in ops:
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            checked += 1
            send = getattr(client, method)
            r = await (send(url) if method in ("get", "delete") else send(url, json={}))
            if r.status_code not in OK_STATUSES:
                leaks.append(f"{method.upper()} {path} → {r.status_code}")
    assert checked > 100, f"проверено подозрительно мало операций: {checked}"
    assert not leaks, "эндпоинты отвечают без токена: " + "; ".join(leaks)


async def test_public_endpoints_still_public(client):
    """Обратная сторона: заявленные публичными маршруты не должны требовать токен."""
    r = await client.get("/health")
    assert r.status_code == 200
    r = await client.get("/auth/password-policy")
    assert r.status_code == 200
