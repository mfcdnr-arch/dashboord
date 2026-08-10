"""Модерация дашборда: submit-review → очередь → approve. Проверяет переходы
статуса публикации (draft → review → published)."""
import json

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

import pytest_asyncio

from app import db
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


async def test_superadmin_can_approve_own(client, superadmin_user):
    """Исключение из разделения обязанностей: владелец системы проходит цикл
    в одиночку. Факт самоодобрения при этом фиксируется в аудите."""
    h = superadmin_user["headers"]
    r = await client.post("/dashboards", headers=h, json={"name": "ztest_super_own"})
    assert r.status_code in (200, 201), r.text
    did = r.json()["id"]
    try:
        await client.post(f"/dashboards/{did}/submit-review", headers=h)
        # в очереди помечен как свой, но одобрять РАЗРЕШЕНО
        r = await client.get("/moderation/queue", headers=h)
        row = next(x for x in r.json() if x["dashboard_id"] == did)
        assert row["own"] is True and row["can_approve"] is True

        r = await client.post(f"/dashboards/{did}/moderate", headers=h, json={"decision": "approve"})
        assert r.status_code == 200, r.text
        r = await client.get(f"/dashboards/{did}", headers=h)
        assert r.json()["dashboard"]["publication_status"] == "published"

        # самоодобрение не замалчивается — оно видно в журнале
        async with db.acquire() as conn:
            new_data = await conn.fetchval(
                "select new_data from audit_log where entity_type='dashboard' and entity_id=$1::uuid "
                "and action='publish' order by created_at desc limit 1", did)
        assert json.loads(new_data)["self_approved"] is True
    finally:
        await purge_dashboard(did)


async def test_double_submit_rejected(client, admin_headers, draft_dashboard):
    await client.post(f"/dashboards/{draft_dashboard}/submit-review", headers=admin_headers)
    r = await client.post(f"/dashboards/{draft_dashboard}/submit-review", headers=admin_headers)
    assert r.status_code == 400  # уже на проверке


async def test_admin_override_publish_closes_pending_request(client, admin_headers, moderator_user,
                                                             draft_dashboard):
    """Прямая публикация админом закрывает висящую заявку на проверку.

    Регрессия (финальный аудит): заявка оставалась pending_moderation навсегда —
    висела в очереди модератора и в /reports/moderation, а повторное «Одобрить»
    перезаписывало version_no версией на момент отправки на проверку.
    """
    await client.post(f"/dashboards/{draft_dashboard}/submit-review", headers=admin_headers)
    r = await client.post(f"/dashboards/{draft_dashboard}/publish", headers=admin_headers)
    assert r.status_code == 200, r.text

    r = await client.get("/moderation/queue", headers=admin_headers)
    assert draft_dashboard not in [x["dashboard_id"] for x in r.json()]

    # и «Одобрить» после override больше не проходит (нечего одобрять)
    r = await client.post(f"/dashboards/{draft_dashboard}/moderate", headers=moderator_user["headers"],
                          json={"decision": "approve"})
    assert r.status_code == 400, r.text
