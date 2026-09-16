"""Адрес клиента для журналов: аудита и журнала входов.

Адрес в журнале — доказательство «кто и откуда», его предъявляют при разборе
инцидента. Поэтому он не может браться из заголовка, который присылает сам
клиент. Nginx перед API ставит `X-Real-IP: $remote_addr` (перезаписывает
присланное клиентом) и дописывает свой адрес в КОНЕЦ `X-Forwarded-For`
(`$proxy_add_x_forwarded_for`) — значит НАЧАЛО списка это то, что прислал
клиент, и доверять ему нельзя (находка аудита 4.8: читалось именно начало).

Правило одно: заголовкам верим ТОЛЬКО когда запрос пришёл от доверенного
прокси; иначе берём адрес самого отправителя. Живёт в одном месте, потому
что журналов два (`audit_log` через GUC и `login_events` напрямую) — копия
правила однажды разошлась бы с оригиналом.
"""
from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from functools import lru_cache

from .config import settings

# Умолчание — приватные сети и loopback. Адрес контейнера nginx в docker-сети
# заранее неизвестен (compose волен выдать любую подсеть), а слишком узкий
# список молча превратил бы журнал в перечень адресов самого прокси — потеря
# данных, которую замечают не сразу. Сузить до конкретного адреса прокси можно
# переменной TRUSTED_PROXIES. В прод-стеке порт API наружу не опубликован
# (docker-compose.prod.yml), то есть прийти мимо nginx можно только изнутри.
DEFAULT_TRUSTED = "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"

_REAL = "x-real-ip"
_FORWARDED = "x-forwarded-for"


@lru_cache(maxsize=8)
def _networks(spec: str) -> tuple:
    nets = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            # Кривая запись в настройке не должна ронять приложение. Пустой в
            # итоге список означает «не доверяем никому» — журнал запишет адрес
            # отправителя, то есть промах настройки уводит в безопасную сторону.
            continue
    return tuple(nets)


def normalize(value: str | None) -> str | None:
    """Строку из заголовка — в адрес; всё, что адресом не является, отбрасываем.

    Поля журналов имеют тип `text`, поэтому СУБД приняла бы любую строку: без
    этой проверки клиент писал бы в журнал произвольный текст.
    """
    if not value:
        return None
    v = value.strip().strip('"')
    if v.startswith("[") and v.endswith("]"):  # IPv6 в скобках: [2001:db8::1]
        v = v[1:-1]
    try:
        return str(ipaddress.ip_address(v))
    except ValueError:
        return None


def is_trusted(peer: str | None) -> bool:
    """Доверенный ли отправитель — то есть наш ли это прокси."""
    addr = normalize(peer)
    if addr is None:
        return False
    ip = ipaddress.ip_address(addr)
    return any(ip in net for net in _networks(settings.trusted_proxies or DEFAULT_TRUSTED))


def resolve(peer: str | None, real_ip: str | None, forwarded_for: str | None) -> str | None:
    """Адрес клиента по адресу отправителя и заголовкам прокси."""
    direct = normalize(peer)
    if direct is None:
        return None
    if not is_trusted(direct):
        # Запрос пришёл мимо прокси — заголовки целиком в руках отправителя.
        return direct
    real = normalize(real_ip)
    if real:
        return real
    for part in reversed((forwarded_for or "").split(",")):
        # Последний элемент дописал доверенный прокси; начало прислал клиент.
        candidate = normalize(part)
        if candidate:
            return candidate
    # Заголовков нет или в них мусор: адрес прокси честнее пустоты — он
    # отвечает хотя бы на то, откуда запрос пришёл к приложению.
    return direct


def from_pairs(peer: str | None, headers: Iterable[tuple[str, str]]) -> str | None:
    """Общий разбор для обоих путей (ASGI-scope и Request) — чтобы журналы не
    разошлись из-за разного обращения с повторяющимися заголовками."""
    real: str | None = None
    forwarded: list[str] = []
    for key, value in headers:
        low = key.lower()
        if low == _REAL:
            real = value  # при повторах ближайший к нам — последний
        elif low == _FORWARDED:
            forwarded.append(value)
    return resolve(peer, real, ", ".join(forwarded) if forwarded else None)


def from_scope(scope) -> str | None:
    client = scope.get("client")
    pairs = ((k.decode("latin-1"), v.decode("latin-1", "ignore"))
             for k, v in (scope.get("headers") or []))
    return from_pairs(client[0] if client else None, pairs)


def from_request(request) -> str | None:
    return from_pairs(request.client.host if request.client else None, request.headers.items())
