"""Чистка ленты уведомлений: события «в никуда» и прочитанное старьё.

Уведомления копились без ограничения: на стенде их набралось 4460, из них 4430
указывали на давно удалённые сущности. Колокольчик показывал «99+», а клик по
такому уведомлению приводил в пустоту — ленту в таком виде перестают читать.

Главное правило, которое проверяется здесь: НЕПРОЧИТАННОЕ не удаляется никогда,
каким бы старым оно ни было. Это единственное, на что человек ещё может
отреагировать.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from app.modules.maintenance import service as maint
from app.modules.notifications import service as notif


async def _event(conn, org_id, user_id, entity_id, *, days_ago=0, read=False):
    ev = await notif.notify(
        conn, org_id, "data.stale", "object", str(entity_id), {"object_name": "ztest"}, [user_id])
    await conn.execute(
        "update notification_events set created_at = now() - make_interval(days => $2) where id=$1::uuid",
        ev, days_ago)
    if read:
        await conn.execute(
            "update notification_recipients set is_read = true where notification_event_id=$1::uuid", ev)
    return ev


async def test_pruning_removes_dead_ends_and_keeps_unread(client, admin_headers, ids):
    async with db.acquire() as conn:
        uid = await conn.fetchval("select id from users where login='admin'")
        obj = await conn.fetchval(
            "insert into objects(organization_id, name, created_by) values($1,'ztest_prune_obj',$2) returning id",
            ids["org"], uid)
        # Событие об удалённом объекте: ведёт в никуда.
        gone = await conn.fetchval(
            "insert into objects(organization_id, name, created_by) values($1,'ztest_prune_gone',$2) returning id",
            ids["org"], uid)
        dead = await _event(conn, ids["org"], uid, gone)
        await conn.execute("delete from objects where id=$1", gone)

        old_read = await _event(conn, ids["org"], uid, obj, days_ago=200, read=True)
        old_unread = await _event(conn, ids["org"], uid, obj, days_ago=200, read=False)
        fresh_read = await _event(conn, ids["org"], uid, obj, days_ago=1, read=True)

        try:
            res = await maint.prune_notifications(conn, ids["org"])
            assert res["orphaned"] >= 1 and res["old_read"] >= 1, res

            alive = await conn.fetch(
                "select id from notification_events where id = any($1::uuid[])",
                [dead, old_read, old_unread, fresh_read])
            ids_alive = {str(r["id"]) for r in alive}

            assert dead not in ids_alive, "событие об удалённой сущности — тупик, его нет смысла хранить"
            assert old_read not in ids_alive, "прочитанное старьё убирается"
            assert old_unread in ids_alive, "НЕПРОЧИТАННОЕ не удаляется, даже если ему полгода"
            assert fresh_read in ids_alive, "свежее прочитанное остаётся"
        finally:
            await conn.execute(
                "delete from notification_recipients where notification_event_id in "
                "(select id from notification_events where entity_id=$1::uuid)", obj)
            await conn.execute("delete from notification_events where entity_id=$1::uuid", obj)
            await conn.execute("delete from objects where id=$1", obj)
