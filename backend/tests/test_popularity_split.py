"""Отчёт «Популярность»: итог сверху и таблица снизу считают одно и то же.

🔴 Раньше они считали РАЗНОЕ: итог — все записи просмотра, таблица — только
существующие дашборды (join). У заказчика это дало «38 просмотров» над
таблицей, где строки давали 5: 24 отчёта успели удалить, а их просмотры
остались в журнале — и правильно остались, журнал не переписывают задним
числом. Неверным был не подсчёт, а молчание: два числа про разное на одном
экране без единого слова о том, про что каждое.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from app.modules.reports import service as reports


async def test_totals_split_into_existing_and_deleted(client, admin_headers, ids):
    """Просмотры удалённого отчёта остаются в итоге и названы отдельно."""
    org = ids["org"]
    async with db.acquire() as conn:
        actor = await conn.fetchval("select id from users where organization_id=$1 limit 1", org)
        live = await conn.fetchval(
            "insert into dashboards(organization_id, name, created_by) "
            "values($1,'ztest_pop_live',$2) returning id", org, actor)
        # Отчёт, который «удалили»: просмотры на его id есть, самого его нет.
        gone_id = await conn.fetchval("select gen_random_uuid()")
        for eid, times in ((live, 2), (gone_id, 3)):
            for _ in range(times):
                await conn.execute(
                    "insert into audit_log(organization_id, actor_user_id, action, entity_type, entity_id) "
                    "values($1,$2,'view','dashboard',$3)", org, actor, eid)

        try:
            rep = await reports.popularity(conn, org)

            mine = [d for d in rep["top_dashboards"] if d["name"] == "ztest_pop_live"]
            assert mine and mine[0]["views"] == 2
            # Дата создания нужна, чтобы различать ОДНОИМЁННЫЕ отчёты.
            assert mine[0]["created_at"], "без даты создания одноимённые неразличимы"

            # Итог включает просмотры удалённого, «existing» — нет, и разница названа.
            assert rep["totals"]["views"] >= 5
            assert rep["existing"]["views"] + rep["deleted"]["views"] == rep["totals"]["views"], \
                "итог обязан раскладываться на живые и удалённые без остатка"
            assert rep["deleted"]["views"] >= 3
            assert rep["deleted"]["dashboards"] >= 1

            # Сумма строк таблицы сходится с «existing» (пока не сработал потолок топ-10).
            shown = sum(d["views"] for d in rep["top_dashboards"])
            assert shown + rep["others_views"] == rep["existing"]["views"], \
                "то, что видно в таблице, плюс «остальные» обязано давать просмотры живых отчётов"
        finally:
            await conn.execute("delete from audit_log where entity_id = any($1::uuid[])", [live, gone_id])
            await conn.execute("delete from securable_objects where object_id=$1", live)
            await conn.execute("delete from dashboards where id=$1", live)
