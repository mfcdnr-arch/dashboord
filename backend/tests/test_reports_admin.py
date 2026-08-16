"""Раздел «Отчёты»: период, выгрузка и очистка истории (п. 4 списка заказчика).

Три вещи, которые здесь проверяются и стоят дороже самой функции:

1. **Период реально фильтрует.** Раньше он был зашит (30 дней), и вопрос «что
   было в июле» задать было нечем.
2. **Выгрузка совпадает с экраном.** Файл считается тем же кодом, что и отчёт;
   если бы они разошлись, человек отправил бы наверх не то, что видел.
3. **Очистка не трогает журнал действий.** Аудит существует, чтобы отвечать
   «кто это сделал»; журнал, из которого можно стереть неудобную строку, не
   отвечает на этот вопрос вовсе. Плюс сама очистка попадает в аудит.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db


@pytest.fixture
async def old_events(ids):
    """Пара «старых» записей журнала входов и одна свежая."""
    async with db.acquire() as conn:
        await conn.execute("delete from login_events where user_agent='ztest-reports'")
        for days in (400, 400, 1):
            await conn.execute(
                "insert into login_events(organization_id, user_id, login, success, ip, user_agent, created_at) "
                "values($1, $2, 'ztest_rep', true, '127.0.0.1', 'ztest-reports', now() - make_interval(days => $3))",
                ids["org"], ids["admin"], days)
    yield
    async with db.acquire() as conn:
        await conn.execute("delete from login_events where user_agent='ztest-reports'")


async def test_period_filters_attendance(client, admin_headers, old_events):
    """Тот же журнал, разные диапазоны — разные числа."""
    wide = (await client.get("/reports/attendance?from=2025-01-01", headers=admin_headers)).json()
    narrow = (await client.get("/reports/attendance", headers=admin_headers)).json()
    assert wide["totals"]["logins"] >= narrow["totals"]["logins"] + 2, \
        "две записи 400-дневной давности должны попадать только в широкий период"
    assert wide["period"]["from"] == "2025-01-01"
    assert wide["period"]["clamped"] is False
    assert narrow["period"]["days"] == 30, "по умолчанию — последние 30 дней"

    # Слишком широкий запрос обрезается, но об этом СКАЗАНО: молчаливая подмена
    # периода — это показ не тех данных.
    huge = (await client.get("/reports/attendance?from=2010-01-01", headers=admin_headers)).json()
    assert huge["period"]["clamped"] is True
    assert huge["period"]["from"] > "2010-01-01"


async def test_export_matches_the_screen(client, admin_headers, old_events):
    """CSV собирается из того же отчёта: итог в файле равен итогу на экране."""
    rep = (await client.get("/reports/attendance?from=2025-01-01", headers=admin_headers)).json()
    r = await client.get("/reports/attendance/export.csv?from=2025-01-01", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert "attachment" in r.headers.get("content-disposition", "")
    text = r.content.decode("utf-8-sig")
    last = [c for c in text.strip().splitlines()[-1].split(";")]
    assert last[0] == "Итого"
    assert int(last[1]) == rep["totals"]["logins"], "файл не должен расходиться с экраном"

    # Формат xlsx отдаётся как файл книги, а не как текст.
    x = await client.get("/reports/popularity/export.xlsx", headers=admin_headers)
    assert x.status_code == 200
    assert x.content[:2] == b"PK", "xlsx — это zip-контейнер"

    # Неизвестный отчёт и формат — понятный отказ, а не пустой файл.
    assert (await client.get("/reports/nonexistent/export.csv", headers=admin_headers)).status_code == 404
    assert (await client.get("/reports/attendance/export.pdf", headers=admin_headers)).status_code == 404


async def test_history_purge_is_superadmin_only(client, admin_headers, viewer, superadmin_headers):
    for headers in (viewer["headers"], admin_headers):
        assert (await client.get("/reports/history", headers=headers)).status_code == 403
        r = await client.post("/reports/history/purge", headers=headers, json={"kinds": ["logins"]})
        assert r.status_code == 403
    assert (await client.get("/reports/history", headers=superadmin_headers)).status_code == 200


async def test_purge_removes_old_but_keeps_fresh_and_audit(client, superadmin_headers, old_events, ids):
    """Удаляется только старое; журнал действий не трогается, а очистка в нём остаётся."""
    async with db.acquire() as conn:
        audit_before = await conn.fetchval(
            "select count(*) from audit_log where organization_id=$1 and action <> 'view'", ids["org"])

    stats = (await client.get("/reports/history?older_than_days=180", headers=superadmin_headers)).json()
    logins = next(k for k in stats["kinds"] if k["kind"] == "logins")
    assert logins["removable"] >= 2
    assert stats["protected_audit_events"] >= audit_before - 1, \
        "экран обязан показывать, сколько событий НЕ будет удалено"

    r = await client.post("/reports/history/purge", headers=superadmin_headers,
                          json={"kinds": ["logins"], "older_than_days": 180})
    assert r.status_code == 200, r.text
    assert r.json()["removed"]["logins"] >= 2

    async with db.acquire() as conn:
        left = await conn.fetchval("select count(*) from login_events where user_agent='ztest-reports'")
        audit_after = await conn.fetchval(
            "select count(*) from audit_log where organization_id=$1 and action <> 'view'", ids["org"])
        purge_logged = await conn.fetchval(
            "select count(*) from audit_log where entity_type='history' and organization_id=$1", ids["org"])
    assert left == 1, "свежая запись должна остаться"
    assert audit_after > audit_before, "журнал действий не уменьшается, а пополняется записью об очистке"
    assert purge_logged >= 1, "сама очистка обязана остаться в журнале"


async def test_purge_refuses_unknown_kind_and_empty_choice(client, superadmin_headers):
    assert (await client.post("/reports/history/purge", headers=superadmin_headers,
                              json={"kinds": []})).status_code == 400
    r = await client.post("/reports/history/purge", headers=superadmin_headers,
                          json={"kinds": ["audit"]})
    assert r.status_code == 400
    assert "audit" in r.json()["detail"], "нужно назвать, что именно не принято"


async def test_purge_floor_protects_fresh_history(client, superadmin_headers, old_events):
    """Порог ниже 30 дней поднимается: свежую историю стирать нельзя."""
    r = await client.post("/reports/history/purge", headers=superadmin_headers,
                          json={"kinds": ["logins"], "older_than_days": 0})
    assert r.status_code == 200
    assert r.json()["older_than_days"] == 30
    async with db.acquire() as conn:
        left = await conn.fetchval("select count(*) from login_events where user_agent='ztest-reports'")
    assert left == 1, "вчерашняя запись обязана уцелеть даже при пороге 0"
