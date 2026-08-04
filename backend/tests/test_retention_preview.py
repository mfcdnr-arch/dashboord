"""Ретенция: предпросмотр показывает, ЧТО именно будет удалено.

Раньше `/maintenance/retention/preview` отдавал только счётчики, а сам вызов был
доступен лишь через API — администратор не мог из интерфейса увидеть состав
удаляемого перед необратимой операцией (финальный аудит, В-6).
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_preview_lists_releases_and_affected_dashboards(client, admin_headers, seed_dataset):
    # окно 1 месяц — выпуски seed_dataset (январь/февраль 2026) заведомо старше
    r = await client.get("/maintenance/retention/preview?months=1", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["releases"] >= 2 and body["values"] > 0
    items = body["items"]
    assert items, "предпросмотр должен перечислять конкретные выпуски"
    ours = [i for i in items if i["code"] == seed_dataset["code"]]
    assert len(ours) >= 2
    for it in ours:
        assert it["period"] and it["object_name"] and it["values_count"] > 0
    assert "affected_dashboards" in body


async def test_preview_disabled_when_window_is_zero(client, admin_headers):
    """months=0 нельзя передать (ge=1) — выключенность приходит из настроек орг."""
    r = await client.get("/maintenance/retention/preview?months=0", headers=admin_headers)
    assert r.status_code == 422


async def test_preview_requires_admin(client, viewer):
    r = await client.get("/maintenance/retention/preview", headers=viewer["headers"])
    assert r.status_code == 403
