"""Выгрузка журналов в CSV/XLSX (admin): аудит действий и журнал входов."""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

XLSX_SIG = b"PK\x03\x04"  # zip-сигнатура (xlsx — это zip)


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
