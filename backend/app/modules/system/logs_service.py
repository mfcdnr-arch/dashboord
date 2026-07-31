"""Просмотр серверных логов в UI — через уже имеющийся в проекте Loki
(monitoring-стек), без дублирования инфраструктуры и без docker.sock в
контейнере API. Если мониторинг не включён — Loki недоступен, отдаём
понятную подсказку вместо ошибки 500 (см. LogsUnavailable)."""
from __future__ import annotations

import time

import httpx

LOKI_URL = "http://loki:3100"
# Имена сервисов = ключи docker-compose (метка `service` в promtail-config.yml,
# из com.docker.compose.service — Docker Compose проставляет её сам).
KNOWN_SERVICES = ("api", "worker", "web", "postgres", "redis", "minio")


class LogsUnavailable(Exception):
    """Loki недоступен — мониторинг, скорее всего, не включён на этой инсталляции."""


async def query_logs(service: str, minutes: int, limit: int, query: str | None) -> list[dict]:
    if service not in KNOWN_SERVICES:
        raise ValueError(f"Неизвестный сервис: {service}. Доступны: {', '.join(KNOWN_SERVICES)}")
    end_ns = time.time_ns()
    start_ns = end_ns - minutes * 60 * 1_000_000_000
    expr = f'{{service="{service}"}}'
    if query:
        expr += f' |= "{query.replace(chr(34), chr(92) + chr(34))}"'
    params: dict[str, str | int] = {
        "query": expr, "limit": limit, "start": start_ns, "end": end_ns, "direction": "backward"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            r = await http.get(f"{LOKI_URL}/loki/api/v1/query_range", params=params)
            r.raise_for_status()
    except httpx.HTTPError as e:
        raise LogsUnavailable(str(e)) from e
    lines = []
    for stream in r.json().get("data", {}).get("result", []):
        for ts_ns, line in stream.get("values", []):
            lines.append({"ts_ns": int(ts_ns), "line": line})
    lines.sort(key=lambda x: x["ts_ns"], reverse=True)
    return lines[:limit]
