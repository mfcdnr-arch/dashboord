"""RLS видимости дашбордов: непривилегированный пользователь не видит чужой
дашборд, пока ему не выдан грант. Критично для госсистемы — регрессия здесь
означает утечку доступа."""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

import pytest_asyncio

from conftest import purge_dashboard


@pytest_asyncio.fixture
async def dashboard(client, admin_headers):
    """Дашборд, созданный admin. Удаляется после теста (API-delete нет — чистим SQL)."""
    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_rls_dash"})
    assert r.status_code in (200, 201), r.text
    did = r.json()["id"]
    yield did
    await purge_dashboard(did)


async def test_viewer_cannot_see_ungranted(client, viewer, dashboard):
    # нет в списке
    r = await client.get("/dashboards", headers=viewer["headers"])
    assert r.status_code == 200
    ids = [d["id"] for d in r.json()["items"]]
    assert dashboard not in ids
    # прямой доступ → 404
    r = await client.get(f"/dashboards/{dashboard}", headers=viewer["headers"])
    assert r.status_code == 404


async def test_viewer_sees_after_grant_and_publish(client, admin_headers, viewer, dashboard):
    # админ выдаёт грант пользователю
    r = await client.post(f"/dashboards/{dashboard}/grants", headers=admin_headers,
                        json={"grantee_type": "user", "user_id": viewer["id"]})
    assert r.status_code in (200, 201), r.text
    # ВАЖНО: непривилегированный видит гранто­ванный дашборд только ОПУБЛИКОВАННЫМ
    # (модерационный гейт). До публикации — не виден.
    r = await client.get("/dashboards", headers=viewer["headers"])
    assert dashboard not in [d["id"] for d in r.json()["items"]]
    # публикуем (admin override) — теперь виден в списке и напрямую
    r = await client.post(f"/dashboards/{dashboard}/publish", headers=admin_headers)
    assert r.status_code == 200, r.text
    r = await client.get("/dashboards", headers=viewer["headers"])
    assert dashboard in [d["id"] for d in r.json()["items"]]
    r = await client.get(f"/dashboards/{dashboard}", headers=viewer["headers"])
    assert r.status_code == 200


async def test_viewer_cannot_manage(client, viewer, dashboard):
    # непривилегированный не может выдавать гранты (запись под manage)
    r = await client.post(f"/dashboards/{dashboard}/grants", headers=viewer["headers"],
                        json={"grantee_type": "user", "user_id": viewer["id"]})
    assert r.status_code in (403, 404)
