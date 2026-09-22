"""Уведомления: пропущенный отчёт и заявка на проверку.

Две дыры, найденные аудитом 15.08.2026: тип события «Ожидаемые данные не
поступили» был объявлен, но не создавался никогда (проверка свежести смотрит
только на возраст последней загрузки вообще), а заявка на модерацию лежала в
очереди, пока модератор сам туда не заглянет.
"""
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

import pytest_asyncio

from app import db
from app.modules.maintenance import service as maint


def _weekly(n: int, start=date(2026, 4, 1)) -> list:
    return [start + timedelta(days=7 * i) for i in range(n)]


def test_cadence_needs_enough_history():
    """На двух-трёх отчётах ритм — случайность, а не закономерность."""
    assert maint.infer_cadence(_weekly(3)) is None
    assert maint.infer_cadence(_weekly(4)) == 7


def test_cadence_ignores_irregular_uploads():
    """Форма приходит как придётся — говорить о пропуске нельзя."""
    start = date(2026, 4, 1)
    chaotic = [start, start + timedelta(days=3), start + timedelta(days=30),
               start + timedelta(days=33), start + timedelta(days=90)]
    assert maint.infer_cadence(chaotic) is None


def test_cadence_tolerates_small_shifts():
    """Отчёт то в пятницу, то в понедельник — ритм всё ещё недельный."""
    start = date(2026, 4, 1)
    shifted = [start, start + timedelta(days=7), start + timedelta(days=13),
               start + timedelta(days=21), start + timedelta(days=28)]
    assert maint.infer_cadence(shifted) == 7


def test_monthly_cadence_detected():
    start = date(2026, 1, 31)
    monthly = [start, date(2026, 3, 2), date(2026, 4, 1), date(2026, 5, 1), date(2026, 5, 31)]
    assert maint.infer_cadence(monthly) in (29, 30, 31)


@pytest_asyncio.fixture
async def weekly_object(client, admin_headers, ids):
    """Объект с недельными выпусками; последний — намеренно просроченный."""
    r = await client.post("/objects", headers=admin_headers, json={"name": "ztest_ritm_obj"})
    oid = r.json()["id"]
    async with db.acquire() as conn:
        uid = await conn.fetchval("select id from users where login='admin'")
        # 15 недель подряд, последняя — три недели назад: один отчёт пропущен.
        last = date.today() - timedelta(days=21)
        for i in range(15):
            period = last - timedelta(days=7 * (14 - i))
            await conn.execute(
                "insert into dataset_releases(organization_id, object_id, code, name, status, "
                "reporting_period_start, created_by) values($1,$2::uuid,'ztest_ritm','Форма','validated',$3,$4)",
                ids["org"], oid, period, uid)
    yield oid
    async with db.acquire() as conn:
        await conn.execute("delete from notification_recipients where notification_event_id in "
                           "(select id from notification_events where entity_id=$1::uuid)", oid)
        await conn.execute("delete from notification_events where entity_id=$1::uuid", oid)
        await conn.execute("delete from dataset_releases where object_id=$1::uuid", oid)
        await conn.execute("delete from objects where id=$1::uuid", oid)


async def test_missing_weekly_report_creates_notification(weekly_object, ids):
    """Форма приходила еженедельно и не пришла — это событие, а не тишина."""
    async with db.acquire() as conn:
        res = await maint.check_cadence(conn, ids["org"])
        mine = [m for m in res["missing"] if m["dataset_code"] == "ztest_ritm"]
        assert mine, res
        assert mine[0]["cadence_days"] == 7
        assert mine[0]["periods_seen"] == 15
        assert mine[0]["overdue_days"] >= 7

        ev = await conn.fetchrow(
            "select event_type, payload from notification_events "
            "where entity_id=$1::uuid and event_type='data.missing'", weekly_object)
        assert ev is not None, "уведомление должно быть создано"

        # Антидубль: повторный прогон в тот же цикл не плодит уведомления.
        before = await conn.fetchval(
            "select count(*) from notification_events where entity_id=$1::uuid", weekly_object)
        await maint.check_cadence(conn, ids["org"])
        after = await conn.fetchval(
            "select count(*) from notification_events where entity_id=$1::uuid", weekly_object)
        assert after == before


async def test_review_request_notifies_moderators(client, admin_headers, moderator_user, ids):
    """Заявка на проверку доходит до модератора, а не ждёт, пока он заглянет сам."""
    r = await client.post("/dashboards", headers=admin_headers,
                          json={"name": "ztest_review_notice"})
    did = r.json()["id"]
    try:
        r = await client.post(f"/dashboards/{did}/submit-review", headers=admin_headers)
        assert r.status_code == 200, r.text

        async with db.acquire() as conn:
            ev = await conn.fetchrow(
                "select id, payload from notification_events "
                "where entity_id=$1::uuid and event_type='dashboard.review_requested'", did)
            assert ev is not None, "модератор должен узнать о заявке"
            got = await conn.fetch(
                "select user_id from notification_recipients where notification_event_id=$1", ev["id"])
            recipients = {str(g["user_id"]) for g in got}
            assert str(moderator_user["id"]) in recipients
            # Автору заявки уведомление ни к чему — он её и отправил.
            admin_id = await conn.fetchval("select id from users where login='admin'")
            assert str(admin_id) not in recipients
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from notification_recipients where notification_event_id in "
                               "(select id from notification_events where entity_id=$1::uuid)", did)
            await conn.execute("delete from notification_events where entity_id=$1::uuid", did)
            await conn.execute("delete from publication_requests where dashboard_id=$1::uuid", did)
            await conn.execute("delete from dashboard_versions where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)


@pytest_asyncio.fixture
async def gapped_object(client, admin_headers, ids):
    """Объект, где неделя ВЫПАЛА, а ряд продолжился.

    Ровно случай «Статистики услуг ДНР»: отчёты за 05.08, 12.08, 19.08, 02.09 и
    09.09 — недели 26.08 нет. Последний отчёт свежий, то есть проверка хвоста
    молчит, и до 22.09.2026 о пропуске не говорил никто.
    """
    r = await client.post("/objects", headers=admin_headers, json={"name": "ztest_gap_obj"})
    oid = r.json()["id"]
    async with db.acquire() as conn:
        uid = await conn.fetchval("select id from users where login='admin'")
        last = date.today()
        # Десять недель подряд, недели «-14» нет. Ряд намеренно длинный: на
        # коротком удаление ещё одного отчёта переводит МЕДИАНУ интервалов с 7
        # на 14, форма начинает выглядеть двухнедельной, и пропусков в ней
        # «нет» — тест проверял бы не то, что думает.
        weeks = [70, 63, 56, 49, 42, 35, 28, 21, 7, 0]
        for back in weeks:
            await conn.execute(
                "insert into dataset_releases(organization_id, object_id, code, name, status, "
                "reporting_period_start, created_by) "
                "values($1,$2::uuid,'ztest_gap','Форма','validated',$3,$4)",
                ids["org"], oid, last - timedelta(days=back), uid)
    yield oid
    async with db.acquire() as conn:
        await conn.execute("delete from notification_recipients where notification_event_id in "
                           "(select id from notification_events where entity_id=$1::uuid)", oid)
        await conn.execute("delete from notification_events where entity_id=$1::uuid", oid)
        await conn.execute("delete from dataset_releases where object_id=$1::uuid", oid)
        await conn.execute("delete from objects where id=$1::uuid", oid)


async def test_gap_inside_the_series_is_named_by_date(gapped_object, ids):
    """Выпавшая неделя названа датой — и это отдельное событие от просрочки.

    Проверка хвоста смотрит только на то, пришёл ли отчёт ПОСЛЕ последнего;
    пропуск, за которым ряд продолжился, она не видит по устройству. Пока
    события не было, недостача обнаруживалась только тем, что кто-то вручную
    пересчитывал точки на графике.
    """
    async with db.acquire() as conn:
        res = await maint.check_cadence(conn, ids["org"])
        mine = [g for g in res["gaps"] if g["dataset_code"] == "ztest_gap"]
        assert mine, res["gaps"]
        expected = (date.today() - timedelta(days=14)).isoformat()
        assert mine[0]["missing"] == [expected], mine
        assert mine[0]["cadence_days"] == 7

        ev = await conn.fetchval(
            "select payload from notification_events where entity_id=$1::uuid "
            "and event_type='data.gap'", gapped_object)
        assert ev is not None, "о пропуске внутри ряда обязано быть уведомление"

        # Свежий последний отчёт — просрочки нет: два правила не должны
        # рассказывать об одном и том же событии дважды.
        assert not [m for m in res["missing"] if m["dataset_code"] == "ztest_gap"]


async def test_gap_is_announced_once_but_a_new_gap_is_announced_again(gapped_object, ids):
    """Повторять вечно нельзя, промолчать о новой дыре — тоже.

    Пропуск внутри ряда живёт, пока ведомство не пришлёт файл, то есть иногда
    вечно: ежедневное напоминание об одном и том же приучило бы не читать
    уведомления. Зато НОВАЯ дыра обязана прозвучать сразу.
    """
    async with db.acquire() as conn:
        await maint.check_cadence(conn, ids["org"])
        before = await conn.fetchval(
            "select count(*) from notification_events where entity_id=$1::uuid "
            "and event_type='data.gap'", gapped_object)
        await maint.check_cadence(conn, ids["org"])
        assert await conn.fetchval(
            "select count(*) from notification_events where entity_id=$1::uuid "
            "and event_type='data.gap'", gapped_object) == before, "набор дыр не менялся"

        # Убираем ещё один отчёт — дыр стало две, и об этом надо сказать.
        uid = await conn.fetchval("select id from users where login='admin'")
        assert uid is not None
        await conn.execute(
            "delete from dataset_releases where object_id=$1::uuid "
            "and reporting_period_start=$2",
            gapped_object, date.today() - timedelta(days=28))
        res = await maint.check_cadence(conn, ids["org"])
        mine = [g for g in res["gaps"] if g["dataset_code"] == "ztest_gap"]
        assert len(mine[0]["missing"]) == 2, mine
        assert await conn.fetchval(
            "select count(*) from notification_events where entity_id=$1::uuid "
            "and event_type='data.gap'", gapped_object) == before + 1


async def test_overdue_series_is_not_reported_as_an_inner_gap(weekly_object, ids):
    """Хвост и дыра внутри — разные вещи, и путать их нельзя.

    У просроченной формы дыр внутри нет: отчёты шли подряд и кончились. Назови
    мы хвост дырой, человек пошёл бы искать пропущенный файл вместо того, чтобы
    затребовать очередной.
    """
    async with db.acquire() as conn:
        res = await maint.check_cadence(conn, ids["org"])
        assert [m for m in res["missing"] if m["dataset_code"] == "ztest_ritm"], "просрочка обязана быть"
        assert not [g for g in res["gaps"] if g["dataset_code"] == "ztest_ritm"], res["gaps"]
