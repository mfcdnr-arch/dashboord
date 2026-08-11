"""Отмена выпуска данных: снять с использования, не трогая файл.

Заказчик: «а если я не хочу удалять файл, а хочу отменить выпуск данных».
Статус `superseded` был в схеме с самого начала и уважается всеми чтениями,
но выставлялся только автоматически при повторном выпуске за тот же период —
ручной отмены не существовало.

Различие, ради которого написан файл: **отмена обратима и потому не
блокируется**, даже если на данные кто-то опирается (иначе человек с
ошибочными цифрами заперт); **удаление необратимо и потому блокируется**.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db  # noqa: E402
from conftest import purge_dashboard  # noqa: E402

CODE = "ztest_rel_cancel"


async def _make_release(org_id, admin_id, code=CODE, period="2026-03-01"):
    async with db.acquire() as conn:
        obj = await conn.fetchval(
            "select id from objects where organization_id=$1 limit 1", org_id)
        rel = await conn.fetchval(
            "insert into dataset_releases(organization_id, object_id, code, name, status, "
            "reporting_period_start, created_by) "
            "values($1,$2,$3,'Тестовый выпуск','validated',$4::text::date,$5) returning id",
            org_id, obj, code, period, admin_id)
        await conn.execute(
            "insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,value_number) "
            "values($1,0,'Строка','f',7)", rel)
    return str(rel)


async def _purge(code=CODE):
    async with db.acquire() as conn:
        await conn.execute("delete from dataset_releases where code=$1", code)


async def test_cancel_and_restore_release(client, admin_headers, ids):
    """Отмена снимает выпуск с использования, данные и файл остаются;
    возврат ставит его обратно в работу."""
    rid = await _make_release(ids["org"], ids["admin"])
    try:
        r = await client.post(f"/dataset-releases/{rid}/cancel", headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "superseded"

        async with db.acquire() as conn:
            st = await conn.fetchval("select status from dataset_releases where id=$1::uuid", rid)
            vals = await conn.fetchval(
                "select count(*) from dataset_values where dataset_release_id=$1::uuid", rid)
        assert st == "superseded"
        assert vals == 1, "данные не удаляются — выпуск лишь снят с использования"

        # повторная отмена бессмысленна и должна быть отбита
        assert (await client.post(f"/dataset-releases/{rid}/cancel", headers=admin_headers)).status_code == 409

        r = await client.post(f"/dataset-releases/{rid}/restore", headers=admin_headers)
        assert r.status_code == 200, r.text
        async with db.acquire() as conn:
            assert await conn.fetchval("select status from dataset_releases where id=$1::uuid", rid) == "validated"
    finally:
        await _purge()


async def test_cancel_is_allowed_but_warns_about_dependents(client, admin_headers, ids):
    """Отмена ОБРАТИМА, поэтому не блокируется зависимостями — но возвращает
    список затронутого, чтобы человек видел последствия."""
    rid = await _make_release(ids["org"], ids["admin"])
    did = None
    try:
        did = (await client.post("/dashboards", headers=admin_headers,
                                 json={"name": "ztest_rel_dash"})).json()["id"]
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                                 json={"name": "Стр"})).json()["id"]
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                          json={"name": "Карточка", "widget_type": "kpi",
                                "config": {"dataset_code": CODE, "value_field": "f"}})

        r = await client.post(f"/dataset-releases/{rid}/cancel", headers=admin_headers)
        assert r.status_code == 200, "отмена обратима — блокировать нельзя"
        affected = r.json()["affected"]
        assert any("Карточка" in a for a in affected), f"должен предупредить о виджете: {affected}"
    finally:
        if did:
            await purge_dashboard(did)
        await _purge()


async def test_delete_release_is_blocked_by_dependents_and_needs_superadmin(
        client, admin_headers, superadmin_headers, ids):
    """Удаление НЕОБРАТИМО: только суперадминистратор и только если на данные
    никто не опирается."""
    rid = await _make_release(ids["org"], ids["admin"])
    did = None
    try:
        assert (await client.delete(f"/dataset-releases/{rid}", headers=admin_headers)).status_code == 403

        did = (await client.post("/dashboards", headers=admin_headers,
                                 json={"name": "ztest_rel_dash2"})).json()["id"]
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                                 json={"name": "Стр"})).json()["id"]
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                          json={"name": "Карточка2", "widget_type": "kpi",
                                "config": {"dataset_code": CODE, "value_field": "f"}})
        r = await client.delete(f"/dataset-releases/{rid}", headers=superadmin_headers)
        assert r.status_code == 409, r.text
        assert "Карточка2" in r.text

        # убрали зависимость — удаление проходит, файл при этом не трогали
        await purge_dashboard(did); did = None
        assert (await client.delete(f"/dataset-releases/{rid}", headers=superadmin_headers)).status_code == 204
        async with db.acquire() as conn:
            assert await conn.fetchval("select count(*) from dataset_releases where id=$1::uuid", rid) == 0
            assert await conn.fetchval(
                "select count(*) from dataset_values where dataset_release_id=$1::uuid", rid) == 0
    finally:
        if did:
            await purge_dashboard(did)
        await _purge()
