"""Адрес клиента в журналах не подделывается заголовком (находка аудита 4.8).

Nginx перед API дописывает настоящий адрес в КОНЕЦ `X-Forwarded-For`
(`$proxy_add_x_forwarded_for`) и перезаписывает `X-Real-IP` значением
`$remote_addr`. Приложение читало НАЧАЛО списка — то есть ровно то, что
прислал сам клиент. Журнал в госсистеме отвечает на вопрос «кто и откуда» и
предъявляется при разборе инцидента, поэтому проверяем ОБА журнала
(`login_events` и `audit_log`) и обязательно с подменённым заголовком.
"""
import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

from app import clientip, db
from app.main import app

from conftest import BASE, purge_dashboard  # noqa: E402

FORGED = "203.0.113.9"      # что присылает клиент
REAL = "10.0.119.77"        # что видит nginx
PROBE = "ztest_ip_probe"


def _client(peer: str) -> httpx.AsyncClient:
    """Клиент с заданным адресом отправителя (кто стучится в API напрямую)."""
    return httpx.AsyncClient(transport=ASGITransport(app=app, client=(peer, 40000)), base_url=BASE)


async def _last_login_ip(login: str) -> str | None:
    async with db.acquire() as conn:
        return await conn.fetchval(
            "select ip from login_events where login=$1 order by created_at desc limit 1", login)


@pytest_asyncio.fixture
async def clean_probe():
    yield
    async with db.acquire() as conn:
        await conn.execute("delete from login_events where login=$1", PROBE)


@pytest.mark.asyncio(loop_scope="session")
async def test_forged_forwarded_for_does_not_reach_login_journal(clean_probe):
    """Подделка в начале X-Forwarded-For игнорируется — пишется адрес от nginx."""
    async with _client("127.0.0.1") as c:
        await c.post("/auth/login", data={"username": PROBE, "password": "нет"},
                     headers={"X-Forwarded-For": FORGED, "X-Real-IP": REAL})
    assert await _last_login_ip(PROBE) == REAL


@pytest.mark.asyncio(loop_scope="session")
async def test_without_real_ip_last_forwarded_element_wins(clean_probe):
    """Без X-Real-IP берём ПОСЛЕДНИЙ элемент списка: его дописал доверенный nginx."""
    async with _client("127.0.0.1") as c:
        await c.post("/auth/login", data={"username": PROBE, "password": "нет"},
                     headers={"X-Forwarded-For": f"{FORGED}, {REAL}"})
    assert await _last_login_ip(PROBE) == REAL


@pytest.mark.asyncio(loop_scope="session")
async def test_headers_from_untrusted_peer_are_ignored(clean_probe):
    """Запрос пришёл НЕ от прокси (мимо nginx) — заголовкам не верим вовсе."""
    async with _client("198.51.100.4") as c:
        await c.post("/auth/login", data={"username": PROBE, "password": "нет"},
                     headers={"X-Forwarded-For": FORGED, "X-Real-IP": FORGED})
    assert await _last_login_ip(PROBE) == "198.51.100.4"


@pytest.mark.asyncio(loop_scope="session")
async def test_garbage_header_does_not_reach_journal(clean_probe):
    """Мусор вместо адреса не попадает в журнал: в нём должен быть адрес, а не
    произвольная строка от клиента (поле text — СУБД мусор не отвергнет)."""
    async with _client("127.0.0.1") as c:
        await c.post("/auth/login", data={"username": PROBE, "password": "нет"},
                     headers={"X-Real-IP": "not-an-ip", "X-Forwarded-For": "999.1.2.3, srv-01"})
    assert await _last_login_ip(PROBE) == "127.0.0.1"


@pytest.mark.asyncio(loop_scope="session")
async def test_audit_journal_records_real_address(client, admin_headers):
    """Второй журнал — аудит: ip_address пишется триггером из GUC app.client_ip."""
    async with _client("127.0.0.1") as c:
        r = await c.post("/dashboards", headers={**admin_headers, "X-Forwarded-For": FORGED, "X-Real-IP": REAL},
                         json={"name": "ztest_ip_audit"})
        assert r.status_code == 201, r.text
        did = r.json()["id"]
    try:
        async with db.acquire() as conn:
            ip = await conn.fetchval(
                "select ip_address from audit_log where entity_id=$1::uuid order by created_at limit 1", did)
        assert ip != FORGED
        assert ip == REAL
    finally:
        await purge_dashboard(did)
        async with db.acquire() as conn:
            await conn.execute("delete from audit_log where entity_id=$1::uuid", did)


# --- чистая функция разбора: случаи, которые дорого воспроизводить по HTTP ---

def test_resolve_prefers_real_ip_over_forwarded():
    assert clientip.resolve("127.0.0.1", REAL, f"{FORGED}, 172.18.0.5") == REAL


def test_resolve_falls_back_to_peer_when_headers_useless():
    assert clientip.resolve("172.18.0.5", None, None) == "172.18.0.5"
    assert clientip.resolve("172.18.0.5", "   ", ", ,") == "172.18.0.5"


def test_resolve_accepts_ipv6_in_brackets():
    assert clientip.resolve("::1", "[2001:db8::1]", None) == "2001:db8::1"


def test_resolve_ignores_headers_from_public_peer():
    assert clientip.resolve("198.51.100.4", REAL, FORGED) == "198.51.100.4"


def test_trusted_list_can_be_narrowed_by_setting(monkeypatch):
    """Сузить доверие до конкретного адреса прокси можно настройкой — умолчание
    (приватные сети) выбрано лишь потому, что адрес контейнера nginx заранее
    неизвестен."""
    monkeypatch.setattr(clientip.settings, "trusted_proxies", "172.18.0.5")
    assert clientip.resolve("172.18.0.5", REAL, None) == REAL
    # тот же приватный адрес, но не названный в списке, доверия больше не даёт
    assert clientip.resolve("10.0.0.9", REAL, None) == "10.0.0.9"
