"""Календарь поступлений формы (п. 16 второй волны предложений).

Пропуски в ряду отчётов до сих пор были видны только текстом в аналитике
папки. Календарь показывает тот же факт плиткой — и главная опасность здесь
не в раскладке, а в РАСХОЖДЕНИИ: если красная плитка означает пропуск, о
котором соседний экран молчит, спорить придётся уже о самих экранах.

Поэтому тесты проверяют по существу:

1. **Пропуск на плитке совпадает с пропуском в тексте аналитики** — одна дата,
   одно правило, две подачи.
2. **Состояние плитки** различает «пришёл», «выпущен» и «не распознан», а
   зелёная неделя не прячет проблемный файл рядом.
3. **Без ритма пропуски не отмечаются вовсе** — лучше промолчать, чем
   раскрасить полгода красным из-за нерегулярной формы.
4. **Отчёт, сместившийся внутри недели, пропуском не считается** — иначе
   недельная форма, поданная в понедельник вместо пятницы, светилась бы
   красным при полностью закрытой неделе.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db

# Ряд заказчика один в один: недельная форма с одной дырой.
# 22.07 · [29.07 пропущена] · 05.08 · 12.08 · 19.08
PERIODS = ("2026-07-22", "2026-08-05", "2026-08-12", "2026-08-19")


async def _seed(conn, org, admin, periods, released=True, job="succeeded"):
    oid = await conn.fetchval(
        "insert into objects(organization_id,name) values($1,'ztest_cal_obj') returning id", org)
    fid = await conn.fetchval(
        "insert into folders(organization_id,object_id,name) values($1,$2,'ztest_cal_folder') returning id",
        org, oid)
    for i, day in enumerate(periods):
        await _add_doc(conn, org, admin, oid, fid, i, day, released=released, job=job)
    return oid, fid


async def _add_doc(conn, org, admin, oid, fid, i, day, released=True, job="succeeded"):
    doc = await conn.fetchval(
        "insert into documents(organization_id, folder_id, original_filename, source_type, "
        "reporting_period_start, uploaded_by) values($1,$2,$3,'xlsx',$4::text::date,$5) returning id",
        org, fid, f"ztest_cal_{i}.xlsx", day, admin)
    ver = await conn.fetchval(
        "insert into document_versions(document_id, version_no, storage_path, checksum, "
        "file_size_bytes, uploaded_by) values($1,1,$2,$3,1024,$4) returning id",
        doc, f"documents/ztest_cal_{i}", f"ztest_cal_sum_{i}", admin)
    await conn.execute(
        "insert into extraction_jobs(document_version_id, status) "
        "values($1,$2::text::extraction_job_status)", ver, job)
    if released:
        await conn.execute(
            "insert into dataset_releases(organization_id, code, name, status, reporting_period_start, "
            "created_by, object_id, source_document_version_id) "
            "values($1,'ztest_cal_ds','Календарь ДС','released',$2::text::date,$3,$4,$5)",
            org, day, admin, oid, ver)
    return doc


async def _drop(conn, org):
    await conn.execute("delete from dataset_releases where code like 'ztest_cal%'")
    await conn.execute(
        "delete from extraction_jobs where document_version_id in "
        "(select id from document_versions where document_id in "
        " (select id from documents where original_filename like 'ztest_cal%'))")
    await conn.execute(
        "delete from document_versions where document_id in "
        "(select id from documents where original_filename like 'ztest_cal%')")
    await conn.execute("delete from documents where original_filename like 'ztest_cal%'")
    await conn.execute("delete from folders where name like 'ztest_cal%'")
    await conn.execute("delete from objects where name like 'ztest_cal%' and organization_id=$1", org)


@pytest.fixture
async def folder(ids):
    async with db.acquire() as conn:
        await _drop(conn, ids["org"])
        oid, fid = await _seed(conn, ids["org"], ids["admin"], PERIODS)
    yield {"object_id": str(oid), "folder_id": str(fid), "org": ids["org"], "admin": ids["admin"]}
    async with db.acquire() as conn:
        await _drop(conn, ids["org"])


def _week_of(cal, iso_day):
    """Плитка, в которую попала конкретная дата."""
    return next(w for w in cal["weeks"] if w["start"] <= iso_day <= w["end"])


async def test_calendar_gap_matches_analytics_text(client, admin_headers, folder):
    """Пропуск на плитке — тот же, что аналитика печатает строкой.

    Это главная проверка модуля: правило пропуска живёт в одном месте
    (`missing_periods` рядом с `infer_cadence`), и оба экрана обязаны называть
    одну и ту же дату.
    """
    f = folder
    base = f"/objects/{f['object_id']}/folders/{f['folder_id']}"
    cal = (await client.get(f"{base}/calendar", headers=admin_headers)).json()
    an = (await client.get(f"{base}/analytics", headers=admin_headers)).json()

    assert cal["cadence_days"] == 7, "недельный ритм распознан по самой истории"
    assert cal["year"] == 2026

    # Пропущенная неделя названа датой и совпадает с текстом аналитики.
    assert "2026-07-29" in an["data"]["missing_periods"]
    gap = _week_of(cal, "2026-07-29")
    assert gap["state"] == "missing"
    assert gap["missing"] == ["2026-07-29"]
    assert gap["reports"] == []

    # Все даты пропусков календаря содержатся в том, что печатает аналитика
    # (у календаря есть ещё хвост просрочки — его аналитика показывает
    # отдельной строкой «отчёт не поступил», а не в списке дыр).
    inner = [m for w in cal["weeks"] for m in w["missing"] if m < PERIODS[-1]]
    assert set(inner) <= set(an["data"]["missing_periods"])

    # Отчёты попали каждый в свою неделю и все выпущены.
    for day in PERIODS:
        cell = _week_of(cal, day)
        assert cell["state"] == "released", day
        assert [r["period"] for r in cell["reports"]] == [day]
        assert cell["problem"] is False
    assert cal["totals"]["released"] == 4
    assert cal["totals"]["reports"] == 4


async def test_tile_states_and_hidden_problem(client, admin_headers, folder, ids):
    """«Пришёл», «выпущен» и «не распознан» различимы, а зелёная неделя не
    прячет сломанный файл: плитка остаётся зелёной (данные-то есть), но
    помечена проблемой и перечисляет оба файла."""
    f = folder
    async with db.acquire() as conn:
        oid = await conn.fetchval("select id from objects where id=$1::uuid", f["object_id"])
        fid = await conn.fetchval("select id from folders where id=$1::uuid", f["folder_id"])
        # Файл пришёл, но данные из него ещё не выпускали.
        await _add_doc(conn, ids["org"], ids["admin"], oid, fid, 90, "2026-08-26", released=False)
        # Второй файл в НЕДЕЛЮ УЖЕ ВЫПУЩЕННОГО отчёта — и он не распознан.
        await _add_doc(conn, ids["org"], ids["admin"], oid, fid, 91, "2026-08-20",
                       released=False, job="failed")

    cal = (await client.get(f"/objects/{f['object_id']}/folders/{f['folder_id']}/calendar",
                            headers=admin_headers)).json()

    arrived = _week_of(cal, "2026-08-26")
    assert arrived["state"] == "arrived", "файл есть, данных нет — это отдельное состояние"

    mixed = _week_of(cal, "2026-08-19")
    assert mixed["state"] == "released", "выпущенные данные не должны выглядеть отсутствующими"
    assert mixed["problem"] is True, "но сломанный файл рядом обязан быть виден"
    assert {r["state"] for r in mixed["reports"]} == {"released", "failed"}
    assert len(mixed["reports"]) == 2, "подсказка перечисляет оба файла поимённо"


async def test_no_cadence_means_no_missing_marks(client, admin_headers, ids):
    """Ритм не признан — пропуски не отмечаем вовсе.

    Три отчёта вразнобой это не ритм, и красить недели между ними значило бы
    выдумать расписание, которого форма не имеет.
    """
    async with db.acquire() as conn:
        await _drop(conn, ids["org"])
        oid, fid = await _seed(conn, ids["org"], ids["admin"],
                               ("2026-03-02", "2026-04-17", "2026-07-01"))
    try:
        cal = (await client.get(f"/objects/{oid}/folders/{fid}/calendar",
                                headers=admin_headers)).json()
        assert cal["cadence_days"] is None
        assert cal["totals"]["missing"] == 0
        assert all(w["missing"] == [] for w in cal["weeks"])
        assert cal["totals"]["released"] == 3, "сами отчёты при этом видны"
        # Год выбирается по последнему отчёту, а не по календарному «сейчас».
        assert cal["year"] == 2026 and cal["years"] == [2026]
    finally:
        async with db.acquire() as conn:
            await _drop(conn, ids["org"])


async def test_shifted_report_is_not_a_gap(client, admin_headers, ids):
    """Отчёт, сместившийся на день внутри той же недели, пропуском не считается.

    Недельные формы кладут то в пятницу, то в понедельник. Ожидаемая дата и
    фактическая расходятся, но неделя закрыта — плитка обязана быть зелёной.
    """
    async with db.acquire() as conn:
        await _drop(conn, ids["org"])
        # Ритм 7 дней, но последний отчёт пришёл на день позже ожидаемого.
        oid, fid = await _seed(conn, ids["org"], ids["admin"],
                               ("2026-06-01", "2026-06-08", "2026-06-15", "2026-06-23"))
    try:
        cal = (await client.get(f"/objects/{oid}/folders/{fid}/calendar",
                                headers=admin_headers)).json()
        assert cal["cadence_days"] == 7
        cell = _week_of(cal, "2026-06-23")
        assert cell["state"] == "released", "неделя закрыта отчётом, пусть и сместившимся"
        assert [r["period"] for r in cell["reports"]] == ["2026-06-23"]
    finally:
        async with db.acquire() as conn:
            await _drop(conn, ids["org"])


async def test_calendar_access(client, admin_headers, viewer, folder):
    """Календарь — экран модератора; и папка «через» чужой объект не находится."""
    f = folder
    r = await client.get(f"/objects/{f['object_id']}/folders/{f['folder_id']}/calendar",
                         headers=viewer["headers"])
    assert r.status_code == 403

    async with db.acquire() as conn:
        other = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,'ztest_cal_obj2') returning id", f["org"])
    try:
        r = await client.get(f"/objects/{other}/folders/{f['folder_id']}/calendar", headers=admin_headers)
        assert r.status_code == 404
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from objects where id=$1::uuid", other)
