"""Массовая проверка и одобрение показателей.

Показатели заводятся пачками (мастер и предложения по данным создают их
десятками), и десять одинаковых нажатий — ровно та ручная работа, от которой
уходим. Но массовая операция не должна становиться лазейкой: главное здесь —
что ПРАВИЛА НЕ ОСЛАБЛЕНЫ. Свою версию по-прежнему нельзя одобрить, черновик
нельзя одобрить в обход проверки.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db


async def _metric(client, headers, code, name, formula):
    m = await client.post("/metrics", headers=headers, json={"code": code, "name": name})
    mid = m.json()["id"]
    v = await client.post(f"/metrics/{mid}/versions", headers=headers, json={"formula": formula})
    return mid, v.json()["version_id"]


async def test_bulk_validate_then_approve_by_another_person(
        client, admin_headers, moderator_user, seed_dataset):
    """Пачка черновиков проверяется разом, одобряет — другой сотрудник."""
    codes = ["ztest_bulk_a", "ztest_bulk_b"]
    ids = []
    for c in codes:
        ids.append(await _metric(client, moderator_user["headers"], c, f"ztest {c}",
                                 f"SUM(field('{seed_dataset['code']}','plan'))"))
    try:
        vids = [v for _m, v in ids]
        r = await client.post("/metrics/bulk-status", headers=moderator_user["headers"],
                              json={"version_ids": vids, "target": "validated"})
        assert r.status_code == 200, r.text
        assert r.json()["ok"] == 2 and r.json()["skipped"] == 0

        # Одобряет ДРУГОЙ человек — так и должно быть.
        r = await client.post("/metrics/bulk-status", headers=admin_headers,
                              json={"version_ids": vids, "target": "approved"})
        assert r.json()["ok"] == 2, r.json()

        async with db.acquire() as conn:
            rows = await conn.fetch(
                "select status from metric_versions where id = any($1::uuid[])", vids)
        assert {r["status"] for r in rows} == {"approved"}
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from metric_versions where metric_id in "
                               "(select id from metrics where code = any($1::text[]))", codes)
            await conn.execute("delete from metrics where code = any($1::text[])", codes)


async def test_bulk_does_not_let_you_approve_your_own(client, moderator_user, seed_dataset):
    """Массовая операция НЕ обходит разделение обязанностей.

    Иначе «одобрить все» стало бы способом протащить собственную формулу мимо
    проверки — тем самым конфликтом интересов, ради которого правило и введено.
    """
    code = "ztest_bulk_self"
    mid, vid = await _metric(client, moderator_user["headers"], code, "ztest своя версия",
                             f"SUM(field('{seed_dataset['code']}','plan'))")
    try:
        await client.post("/metrics/bulk-status", headers=moderator_user["headers"],
                          json={"version_ids": [vid], "target": "validated"})
        r = await client.post("/metrics/bulk-status", headers=moderator_user["headers"],
                              json={"version_ids": [vid], "target": "approved"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] == 0 and body["skipped"] == 1, body
        assert "собственную" in body["failed"][0]["error"], body

        async with db.acquire() as conn:
            st = await conn.fetchval("select status from metric_versions where id=$1::uuid", vid)
        assert st == "validated", "версия должна остаться проверенной, а не стать одобренной"
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from metric_versions where metric_id=$1::uuid", mid)
            await conn.execute("delete from metrics where id=$1::uuid", mid)


async def test_bulk_cannot_skip_validation_step(client, admin_headers, moderator_user, seed_dataset):
    """Черновик нельзя одобрить в обход проверки — даже пачкой."""
    code = "ztest_bulk_draft"
    mid, vid = await _metric(client, moderator_user["headers"], code, "ztest черновик",
                             f"SUM(field('{seed_dataset['code']}','plan'))")
    try:
        r = await client.post("/metrics/bulk-status", headers=admin_headers,
                              json={"version_ids": [vid], "target": "approved"})
        assert r.json()["ok"] == 0
        assert "проверенную" in r.json()["failed"][0]["error"]
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from metric_versions where metric_id=$1::uuid", mid)
            await conn.execute("delete from metrics where id=$1::uuid", mid)


async def test_pending_lists_what_will_be_touched(client, admin_headers, moderator_user, seed_dataset):
    """Список «что попадёт под операцию» — человек видит его ДО нажатия."""
    code = "ztest_bulk_pending"
    mid, vid = await _metric(client, moderator_user["headers"], code, "ztest в очереди",
                             f"SUM(field('{seed_dataset['code']}','plan'))")
    try:
        r = await client.get("/metrics/pending?target=validated", headers=admin_headers)
        assert any(i["version_id"] == vid for i in r.json()["items"]), r.json()

        await client.post("/metrics/bulk-status", headers=moderator_user["headers"],
                          json={"version_ids": [vid], "target": "validated"})
        r = await client.get("/metrics/pending?target=validated", headers=admin_headers)
        assert not any(i["version_id"] == vid for i in r.json()["items"]), "проверенная уходит из очереди"
        r = await client.get("/metrics/pending?target=approved", headers=admin_headers)
        assert any(i["version_id"] == vid for i in r.json()["items"]), "и появляется в очереди одобрения"
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from metric_versions where metric_id=$1::uuid", mid)
            await conn.execute("delete from metrics where id=$1::uuid", mid)
