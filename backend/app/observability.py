"""Prometheus-метрики приложения (наблюдаемость, self-hosted on-prem).

Экспорт в формате Prometheus по пути /internal/metrics (не /metrics — тот занят
модулем формул-метрик). Скрейпится Prometheus'ом по внутренней docker-сети
(api:8000/internal/metrics); наружу через nginx НЕ проксируется.
"""
from __future__ import annotations

import time

from fastapi import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

METRICS_PATH = "/internal/metrics"

REQUESTS = Counter(
    "http_requests_total", "Всего HTTP-запросов", ["method", "path", "status"])
LATENCY = Histogram(
    "http_request_duration_seconds", "Длительность HTTP-запроса, сек", ["method", "path"])


class PrometheusMiddleware:
    """ASGI-middleware: считает число и длительность HTTP-запросов по ШАБЛОНУ
    маршрута (`/dashboards/{id}`, а не сырой путь) — иначе кардинальность меток
    взорвётся от идентификаторов. Сам /internal/metrics не учитываем."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        holder = {"code": 500}

        async def _send(message):
            if message["type"] == "http.response.start":
                holder["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            route = scope.get("route")
            path = getattr(route, "path", None) or scope.get("path", "")
            if path != METRICS_PATH:
                method = scope.get("method", "")
                REQUESTS.labels(method, path, str(holder["code"])).inc()
                LATENCY.labels(method, path).observe(time.perf_counter() - start)


async def metrics_endpoint() -> Response:
    """Экспозиция метрик в формате Prometheus."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
