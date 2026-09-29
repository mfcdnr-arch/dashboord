"""Каждый корневой адрес API проксируется и в бою, и на дев-стенде.

nginx пропускает к API только перечисленные в регулярном выражении префиксы
(frontend/nginx.locations.conf), остальное отдаёт страницей приложения
(SPA-fallback) с кодом 200. Новый модуль с новым корневым адресом, не
вписанный туда, на дев-стенде работает (vite проксирует по своему списку), а
в бою получает HTML вместо JSON — ошибку, которую видно только на сервере.
Урок записан 10.08 («200 на защищённый маршрут — повод посмотреть nginx»),
а стража не было; завели вместе с направлениями (29.09.2026), у которых свой
корневой адрес `/dashboard-directions`.
"""
import re
from pathlib import Path

from app.main import app

FRONT = Path("/frontend")
if not FRONT.exists():  # локальный прогон вне контейнера
    FRONT = Path(__file__).resolve().parents[2] / "frontend"

# Служебные адреса самого FastAPI — в бою наружу не публикуются.
_INTERNAL = {"openapi.json", "docs", "redoc"}


def _api_prefixes() -> set:
    # Из схемы OpenAPI, как страж авторизации: подключённые модули FastAPI
    # хранит обёртками, и `app.routes` их путей не раскрывает.
    out = set()
    for path in app.openapi()["paths"]:
        head = path.strip("/").split("/", 1)[0]
        if head and not head.startswith("{") and head not in _INTERNAL:
            out.add(head)
    return out


def _nginx_prefixes() -> set:
    text = (FRONT / "nginx.locations.conf").read_text(encoding="utf-8")
    m = re.search(r"location ~ \^/\(([^)]+)\)\(/\|\$\)", text)
    assert m, "в nginx.locations.conf не найдено правило API — страж ослеп бы молча"
    return set(m.group(1).split("|"))


def _vite_prefixes() -> set:
    text = (FRONT / "vite.config.ts").read_text(encoding="utf-8")
    return set(re.findall(r"'/([a-z][a-z0-9-]*)'\s*:", text))


def test_every_api_prefix_reaches_the_api_in_production():
    missing = sorted(_api_prefixes() - _nginx_prefixes())
    assert not missing, (
        f"Префиксы API нет в frontend/nginx.locations.conf: {missing}. В бою такой запрос "
        "получит страницу приложения (200 HTML) вместо ответа API.")


def test_every_api_prefix_is_proxied_on_the_dev_stand():
    missing = sorted(_api_prefixes() - _vite_prefixes())
    assert not missing, f"Префиксы API нет в прокси frontend/vite.config.ts: {missing}"


def test_the_guard_sees_the_routes():
    """Защита от вырождения: если разбор сломается, пустое множество пройдёт всё."""
    assert {"dashboards", "dashboard-directions", "auth"} <= _api_prefixes()
    assert "dashboard-directions" in _nginx_prefixes()
