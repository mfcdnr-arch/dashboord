"""Модерация дашборда: submit-review → очередь → approve. Проверяет переходы
статуса публикации (draft → review → published)."""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

import pytest_asyncio

from conftest import purge_dashboard


@pytest_asyncio.fixture
async def draft_dashboard(client, admin_headers):
    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_mod_dash"})
    assert r.status_code in (200, 201), r.text
    did = r.json()["id"]
    yield did
    await purge_dashboard(did)


async def test_submit_review_puts_in_queue(client, admin_headers, draft_dashboard):
    r = await client.post(f"/dashboards/{draft_dashboard}/submit-review", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["publication_status"] == "review"
    # появился в очереди модерации
    r = await client.get("/moderation/queue", headers=admin_headers)
    assert r.status_code == 200
    ids = [x.get("dashboard_id") or x.get("id") for x in r.json()]
    assert draft_dashboard in ids


async def test_approve_publishes(client, admin_headers, moderator_user, draft_dashboard):
    await client.post(f"/dashboards/{draft_dashboard}/submit-review", headers=admin_headers)
    # Одобряет ДРУГОЙ модератор (свой дашборд одобрять нельзя — разделение обязанностей).
    r = await client.post(f"/dashboards/{draft_dashboard}/moderate", headers=moderator_user["headers"],
                        json={"decision": "approve"})
    assert r.status_code == 200, r.text
    # статус дашборда стал published
    r = await client.get(f"/dashboards/{draft_dashboard}", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["dashboard"]["publication_status"] == "published"


async def test_cannot_approve_own(client, admin_headers, draft_dashboard):
    # Разделение обязанностей: автор не может одобрить собственный дашборд.
    await client.post(f"/dashboards/{draft_dashboard}/submit-review", headers=admin_headers)
    r = await client.post(f"/dashboards/{draft_dashboard}/moderate", headers=admin_headers,
                        json={"decision": "approve"})
    assert r.status_code == 400


async def test_double_submit_rejected(client, admin_headers, draft_dashboard):
    await client.post(f"/dashboards/{draft_dashboard}/submit-review", headers=admin_headers)
    r = await client.post(f"/dashboards/{draft_dashboard}/submit-review", headers=admin_headers)
    assert r.status_code == 400  # уже на проверке
