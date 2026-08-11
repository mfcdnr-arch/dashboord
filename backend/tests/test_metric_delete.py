"""Удаление показателя: каскад версий, отказ пока показатель в работе, права.

Связи с виджетами и с формулами других показателей идут ПО КОДУ (jsonb и AST),
внешних ключей за ними нет — значит проверять их обязано приложение, иначе
удаление молча сломает чужой дашборд.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db  # noqa: E402
from conftest import purge_dashboard  # noqa: E402


async def _metric_with_version(client, headers, code: str, formula: str = "1 + 1") -> str:
    r = await client.post("/metrics", headers=headers, json={"code": code, "name": code})
    assert r.status_code in (200, 201), r.text
    mid = r.json()["id"]
    r = await client.post(f"/metrics/{mid}/versions", headers=headers, json={"formula": formula})
    assert r.status_code in (200, 201), r.text
    return mid


async def _purge(codes):
    async with db.acquire() as conn:
        await conn.execute(
            "delete from metric_versions where metric_id in "
            "(select id from metrics where code = any($1::text[]))", codes)
        await conn.execute("delete from metrics where code = any($1::text[])", codes)


async def test_delete_draft_metric_removes_versions_and_audits(client, admin_headers, superadmin_headers):
    """Обычный случай заказчика: черновик оказался не нужен."""
    code = "ztest_del_draft"
    try:
        mid = await _metric_with_version(client, admin_headers, code)
        r = await client.delete(f"/metrics/{mid}", headers=superadmin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["versions_deleted"] == 1

        assert (await client.get(f"/metrics/{mid}", headers=admin_headers)).status_code == 404
        async with db.acquire() as conn:
            left = await conn.fetchval(
                "select count(*) from metric_versions where metric_id=$1::uuid", mid)
            logged = await conn.fetchval(
                "select count(*) from audit_log where entity_type='metric' and entity_id=$1::uuid "
                "and action='delete'", mid)
        assert left == 0, "версии должны уйти каскадом"
        assert logged == 1, "удаление показателя обязано попасть в журнал"
    finally:
        await _purge([code])


async def test_delete_blocked_while_widget_uses_metric(client, admin_headers, superadmin_headers):
    """Показатель на дашборде удалять нельзя — виджет остался бы без источника."""
    code = "ztest_del_used"
    did = None
    try:
        mid = await _metric_with_version(client, admin_headers, code)
        did = (await client.post("/dashboards", headers=admin_headers,
                                 json={"name": "ztest_del_dash"})).json()["id"]
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                                 json={"name": "Стр"})).json()["id"]
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                          json={"name": "Карточка", "widget_type": "kpi",
                                "config": {"metric_code": code}})

        r = await client.delete(f"/metrics/{mid}", headers=superadmin_headers)
        assert r.status_code == 409, r.text
        assert "Карточка" in r.text and "ztest_del_dash" in r.text, "отказ обязан назвать виновника"

        # после удаления виджета вместе с дашбордом показатель освобождается
        await purge_dashboard(did); did = None
        assert (await client.delete(f"/metrics/{mid}", headers=superadmin_headers)).status_code == 200
    finally:
        if did:
            await purge_dashboard(did)
        await _purge([code])


async def test_delete_blocked_while_other_formula_references_it(client, admin_headers, superadmin_headers):
    """На показатель ссылается формула другого показателя — ссылка внутри AST."""
    base, dep = "ztest_del_base", "ztest_del_dep"
    try:
        mid = await _metric_with_version(client, admin_headers, base)
        await _metric_with_version(client, admin_headers, dep, f"metric('{base}') * 2")

        r = await client.delete(f"/metrics/{mid}", headers=superadmin_headers)
        assert r.status_code == 409, r.text
        assert dep in r.text, "отказ обязан назвать ссылающийся показатель"
    finally:
        await _purge([base, dep])


async def test_delete_only_for_superadmin(client, admin_headers, moderator_user, viewer, superadmin_headers):
    """Удаление показателя сужено до суперадминистратора (решение заказчика
    11.08.2026): остальным доступны обратимые действия — правка формулы,
    новая версия, статус. Показатель, на который где-то ссылаются, они бы
    удалить и так не смогли, но необратимость важнее удобства."""
    code = "ztest_del_rights"
    try:
        mid = await _metric_with_version(client, admin_headers, code)
        for who, headers in (("зритель", viewer["headers"]),
                             ("модератор", moderator_user["headers"]),
                             ("администратор", admin_headers)):
            r = await client.delete(f"/metrics/{mid}", headers=headers)
            assert r.status_code == 403, f"{who} не должен удалять показатель: {r.text}"
        async with db.acquire() as conn:
            assert await conn.fetchval("select count(*) from metrics where id=$1::uuid", mid) == 1

        assert (await client.delete(f"/metrics/{mid}", headers=superadmin_headers)).status_code == 200
    finally:
        await _purge([code])


async def test_delete_missing_metric_gives_404(client, admin_headers, superadmin_headers):
    import uuid
    r = await client.delete(f"/metrics/{uuid.uuid4()}", headers=superadmin_headers)
    assert r.status_code == 404
