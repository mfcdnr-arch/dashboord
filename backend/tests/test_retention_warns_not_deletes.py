"""Ретенция по расписанию предупреждает, а не удаляет (20.09.2026).

До этой правки задача `weekly_retention` каждое воскресенье в 03:00 удаляла
выпуски старше окна сама: необратимо, каскадом по значениям, без подтверждения
и без предпросмотра. Отчётность — то, ради чего система существует, а удаление
было молчаливым: узнать о нём можно было только из ленты постфактум.

Действует тот же принцип, что принят для выпуска данных: автомат готовит,
решение принимает человек. Здесь проверяется именно это — и то, что
предупреждение не превращается в еженедельный шум, за которым перестанут
замечать настоящее.
"""
import datetime as dt

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from app.modules.maintenance import service as maint


async def _make_old_release(conn, org_id, code: str, years_ago: int = 3) -> str:
    """Выпуск заведомо старше любого разумного окна хранения."""
    period = dt.date.today() - dt.timedelta(days=365 * years_ago)
    author = await conn.fetchval("select id from users where organization_id=$1 limit 1", org_id)
    rid = await conn.fetchval(
        "insert into dataset_releases(organization_id, code, name, reporting_period_start, status, created_by) "
        "values($1,$2,$3,$4::text::date,'released',$5) returning id",
        org_id, code, f"ztest ретенция {code}", period.isoformat(), author)
    await conn.execute(
        "insert into dataset_values(dataset_release_id, row_index, row_label, canonical_field_code, value_number) "
        "values($1,0,'ztest строка','ztest_field',1)", rid)
    return str(rid)


async def test_scheduler_warns_and_keeps_the_data(ids):
    """Планировщик считает, зовёт человека и НЕ удаляет ни одного выпуска."""
    org = ids["org"]
    async with db.acquire() as conn:
        rid = await _make_old_release(conn, org, "ztest_ret_keep")
        try:
            before = await conn.fetchval("select count(*) from dataset_releases where organization_id=$1", org)
            res = await maint.warn_retention(conn, org)
            after = await conn.fetchval("select count(*) from dataset_releases where organization_id=$1", org)

            assert after == before, "планировщик удалил данные — он обязан только предупреждать"
            assert await conn.fetchval("select count(*) from dataset_releases where id=$1::uuid", rid) == 1, \
                "старый выпуск исчез после запуска планировщика"
            assert res["notified"] is True and res["releases"] >= 1
            # Значения и самый ранний период нужны в тексте: без них
            # уведомление не отвечает на «что именно под отсечкой».
            assert res["values"] >= 1

            ev = await conn.fetchrow(
                "select event_type, payload from notification_events "
                "where organization_id=$1 and event_type='data.retention_due' "
                "order by created_at desc limit 1", org)
            assert ev is not None, "предупреждение не отправлено"
            recipients = await conn.fetchval(
                "select count(*) from notification_recipients where notification_event_id="
                "(select id from notification_events where organization_id=$1 "
                " and event_type='data.retention_due' order by created_at desc limit 1)", org)
            assert recipients >= 1, "предупреждение никому не адресовано"
        finally:
            await conn.execute("delete from notification_recipients where notification_event_id in "
                               "(select id from notification_events where organization_id=$1 "
                               " and event_type='data.retention_due')", org)
            await conn.execute("delete from notification_events where organization_id=$1 "
                               "and event_type='data.retention_due'", org)
            await conn.execute("delete from dataset_releases where id=$1::uuid", rid)


async def test_no_warning_when_nothing_is_due_or_retention_is_off(ids):
    """Молчит, когда сказать нечего: иначе еженедельный шум, за которым
    пролистают настоящее предупреждение."""
    org = ids["org"]
    async with db.acquire() as conn:
        saved = await conn.fetchval("select settings->>'retention_months' from organizations where id=$1", org)
        try:
            # 1. Ретенция выключена — молчим, даже если старые данные есть.
            await conn.execute(
                "update organizations set settings = jsonb_set(coalesce(settings,'{}'::jsonb),"
                "'{retention_months}', '0'::jsonb) where id=$1", org)
            rid = await _make_old_release(conn, org, "ztest_ret_off")
            res = await maint.warn_retention(conn, org)
            assert res["enabled"] is False and res["notified"] is False
            await conn.execute("delete from dataset_releases where id=$1::uuid", rid)

            # 2. Ретенция включена, но под отсечку ничего не попадает.
            await conn.execute(
                "update organizations set settings = jsonb_set(coalesce(settings,'{}'::jsonb),"
                "'{retention_months}', '600'::jsonb) where id=$1", org)
            res = await maint.warn_retention(conn, org)
            assert res["releases"] == 0 and res["notified"] is False, \
                "предупреждение уходит, когда удалять нечего"
        finally:
            await conn.execute(
                "update organizations set settings = jsonb_set(coalesce(settings,'{}'::jsonb),"
                "'{retention_months}', to_jsonb($2::int)) where id=$1", org, int(saved or 12))


async def test_manual_run_still_deletes(ids):
    """Ручной запуск (кнопка рядом с предпросмотром) удаляет, как и раньше:
    правка убирает автоматику, а не саму возможность очистки."""
    org = ids["org"]
    async with db.acquire() as conn:
        rid = await _make_old_release(conn, org, "ztest_ret_manual")
        res = await maint.run_retention(conn, org, months=12, notify_admins=False)
        assert res["enabled"] is True and res["deleted_releases"] >= 1
        assert await conn.fetchval("select count(*) from dataset_releases where id=$1::uuid", rid) == 0, \
            "ручное удаление перестало работать"


async def test_scheduler_no_longer_calls_the_deleting_function():
    """Страж: планировщик зовёт предупреждение, а не удаление.

    Проверяется ИСХОДНИК задачи: вернуть `run_retention` в cron — правка на
    один символ, и она молча возвращает необратимое авто-удаление."""
    import inspect

    from app.modules.ingestion import worker

    src = inspect.getsource(worker.weekly_retention)
    assert "warn_retention" in src, "планировщик перестал предупреждать о ретенции"
    assert "run_retention" not in src, \
        "в планировщик вернули удаляющую функцию — авто-удаление отчётности снова включено"
