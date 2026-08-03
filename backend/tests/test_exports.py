"""Выгрузка журналов в CSV/XLSX (admin): аудит действий и журнал входов.

Волна B: доступ к аудиту/журналу входов для роли admin (не superadmin) теперь
требует явного гранта (audit_access_grants) — выдаём его сид-admin'у на время
этого файла (autouse), иначе все тесты ниже стали бы падать 403. Сам механизм
гранта/отзыва и негативные сценарии — в test_audit_access.py."""
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import hdr, login

XLSX_SIG = b"PK\x03\x04"  # zip-сигнатура (xlsx — это zip)


@pytest_asyncio.fixture(autouse=True)
async def _grant_admin_audit_access(client, ids):
    sa = hdr(await login(client, "superadmin", "superadmin"))
    await client.post(f"/audit/access/{ids['admin']}", headers=sa)
    yield
    await client.delete(f"/audit/access/{ids['admin']}", headers=sa)


async def test_audit_csv(client, admin_headers):
    r = await client.get("/audit/export.csv", headers=admin_headers)
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    assert r.content[:3] == b"\xef\xbb\xbf"  # BOM UTF-8


async def test_audit_xlsx(client, admin_headers):
    r = await client.get("/audit/export.xlsx", headers=admin_headers)
    assert r.status_code == 200
    assert r.content[:4] == XLSX_SIG


async def test_login_events_csv(client, admin_headers):
    r = await client.get("/login-events/export.csv", headers=admin_headers)
    assert r.status_code == 200
    assert r.content[:3] == b"\xef\xbb\xbf"


async def test_login_events_xlsx(client, admin_headers):
    r = await client.get("/login-events/export.xlsx", headers=admin_headers)
    assert r.status_code == 200
    assert r.content[:4] == XLSX_SIG


async def test_export_requires_admin(client, viewer):
    # непривилегированный (роль user) не должен выгружать журналы
    r = await client.get("/audit/export.csv", headers=viewer["headers"])
    assert r.status_code == 403
