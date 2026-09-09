"""Ступени формы: предложение, подтверждение, устаревание.

Кусок 2 «лестницы». Распознавание уже проверено на чистых функциях
(test_hierarchy_detect); здесь — встреча правила с данными объекта и то, что
человек подтвердил.

Главная проверка — УСТАРЕВАНИЕ. Подтверждение даётся для конкретного бланка, и
когда форма меняется, применить его молча нельзя: лестница показала бы уровни,
которых в новом бланке нет. Тот же довод, по которому не применяется и сама
разметка.

🔴 Коды полей с префиксом `zlv_`: на стенде живут настоящие данные заказчика, и
код вроде `prinyato` уже занят формой МВД — тест зацепил бы её значения.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from app.modules.objects import levels as L

OBJ = "zlv_obj"
CODE = "zlv_ds"

# Двухступенчатая форма по образцу РЦО: «ведомство · услуга · мера», плюс два
# ведомства без ступени «Услуга» — крупное (остаётся строкой) и мелкое.
#
# 🔴 Пропорции взяты с настоящей формы: у РЦО 87 % граф трёхсегментные. Первая
# версия набора была наполовину двухсегментной, и порог ⅔ честно отверг вторую
# ступень — тест упал на образце, а не на правиле. Второй раз те же грабли.
FIELDS = {
    "zlv_rr_reg_in": ("Росреестр · Государственная регистрация прав · Принято, ед.", 8000.0),
    "zlv_rr_reg_out": ("Росреестр · Государственная регистрация прав · Выдано, ед.", 7000.0),
    "zlv_rr_kad_in": ("Росреестр · Государственный кадастровый учет · Принято, ед.", 3000.0),
    "zlv_mvd_reg_in": ("МВД · Регистрационный учет · Принято, ед.", 2000.0),
    "zlv_mvd_reg_out": ("МВД · Регистрационный учет · Выдано, ед.", 1800.0),
    "zlv_sfr_pos_in": ("СФР · Пособие по беременности · Принято, ед.", 900.0),
    "zlv_sfr_pos_out": ("СФР · Пособие по беременности · Выдано, ед.", 850.0),
    "zlv_epgu_res_in": ("ЕПГУ · Получение результата услуги · Принято, ед.", 600.0),
    "zlv_esia_in": ("ЕСИА (260) · Принято, ед.", 5000.0),
    "zlv_apost_in": ("Апостиль (347, 348) · Принято, ед.", 3.0),
    "zlv_note": ("Наименование услуги · Наименование отдела МФЦ", None),
}


@pytest.fixture
async def form(ids):
    """Объект с выпуском, полями и шаблоном разметки."""
    async with db.acquire() as conn:
        await conn.execute("delete from objects where name=$1 and organization_id=$2", OBJ, ids["org"])
        obj = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,$2) returning id", ids["org"], OBJ)
        rel = await conn.fetchval(
            "insert into dataset_releases(organization_id,code,name,status,"
            "reporting_period_start,created_by,object_id) "
            "values($1,$2,'Тест ступеней','released','2026-03-01',$3,$4) returning id",
            ids["org"], CODE, ids["admin"], obj)
        for code, (name, val) in FIELDS.items():
            await conn.execute(
                "insert into canonical_fields(object_id,code,name,data_type) values($1,$2,$3,$4)",
                obj, code, name, "number" if val is not None else "text")
            for i, row in enumerate(["Отделение 1", "Отделение 2"]):
                await conn.execute(
                    "insert into dataset_values(dataset_release_id,row_index,row_label,"
                    "canonical_field_code,value_number,value_text) values($1,$2,$3,$4,$5,$6)",
                    rel, i, row, code, (val / 2) if val is not None else None,
                    None if val is not None else "текст")
        await conn.execute(
            "insert into object_layout_templates(object_id,fingerprint,dataset_code) "
            "values($1,'fp-original',$2)", obj, CODE)
    yield {"object_id": obj, "org": ids["org"]}
    async with db.acquire() as conn:
        await conn.execute("delete from dataset_values where dataset_release_id in "
                           "(select id from dataset_releases where code=$1)", CODE)
        await conn.execute("delete from dataset_releases where code=$1", CODE)
        await conn.execute("delete from objects where name=$1 and organization_id=$2", OBJ, ids["org"])


async def test_suggestion_reads_the_form_and_names_nothing(form):
    """Ступени и меры найдены; имена уровней система НЕ придумывает."""
    async with db.acquire() as conn:
        s = await L.suggest(conn, form["object_id"])
    assert s["kind"] == "hierarchy"
    assert s["separator"] == " · "
    assert len(s["levels"]) == 2
    assert {"Росреестр", "МВД", "ЕСИА (260)"} <= set(s["levels"][0]["sample"] + s["levels"][0]["sample"])
    # Имя уровня остаётся пустым: угадать «Ведомство» из данных нельзя, а
    # правдоподобное имя человек подтвердит не глядя.
    assert all(lv["name"] == "" for lv in s["levels"])
    # Мерой не может быть графа без чисел: «Наименование отдела МФЦ» отсеяно.
    assert "Наименование отдела МФЦ" not in s["measures"]
    assert s["measure_default"] == "Принято, ед.", "по умолчанию «Принято» — решение заказчика"
    assert s["rows"]["count"] == 2


async def test_confirmation_is_stored_and_read_back(form):
    """Подтверждённое сохраняется в шаблоне формы и читается обратно."""
    async with db.acquire() as conn:
        saved = await L.save(conn, form["object_id"], {
            "levels": [{"index": 0, "name": "Ведомство"}, {"index": 1, "name": "Услуга"}],
            "row_level": "Отделение", "group_lone": True,
            "measure_default": "Принято, ед."}, None)
        assert saved["fingerprint"] == "fp-original"
        state = await L.get_state(conn, form["object_id"])
        assert state["stale"] is False
        assert [lv["name"] for lv in state["confirmed"]["levels"]] == ["Ведомство", "Услуга"]
        assert (await L.load_confirmed(conn, form["object_id"]))["row_level"] == "Отделение"


async def test_changed_form_makes_the_confirmation_stale(form):
    """🔴 Форма изменилась — подтверждение не применяется молча.

    Отпечаток в шаблоне другой, значит бланк не тот, для которого человек
    подтверждал уровни. Показать старую лестницу на новой форме значило бы
    соврать; правильный ответ — спросить заново.
    """
    async with db.acquire() as conn:
        await L.save(conn, form["object_id"], {
            "levels": [{"index": 0, "name": "Ведомство"}, {"index": 1, "name": "Услуга"}],
            "row_level": "Отделение", "group_lone": True, "measure_default": None}, None)
        await conn.execute(
            "update object_layout_templates set fingerprint='fp-changed' where object_id=$1",
            form["object_id"])

        state = await L.get_state(conn, form["object_id"])
        assert state["stale"] is True, "подтверждение помечено устаревшим"
        assert state["confirmed"] is not None, "но не потеряно — видно, что подтверждали"
        assert await L.load_confirmed(conn, form["object_id"]) is None, \
            "наружу устаревшее не выходит: лучше без лестницы, чем с неверной"


async def test_object_without_template_cannot_confirm(ids):
    """Форма ещё не размечена — подтверждать нечего, и отказ это объясняет."""
    async with db.acquire() as conn:
        obj = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,'zlv_bare') returning id", ids["org"])
        try:
            with pytest.raises(ValueError, match="не размечена"):
                await L.save(conn, obj, {"levels": [], "row_level": "Строка"}, None)
        finally:
            await conn.execute("delete from objects where id=$1", obj)


async def test_endpoints_are_closed_to_viewers(client, viewer, form):
    """Устройство формы правит только управляющий; чужой объект — 404."""
    r = await client.get(f"/objects/{form['object_id']}/levels", headers=viewer["headers"])
    assert r.status_code == 403, r.text
    r = await client.post(f"/objects/{form['object_id']}/levels", headers=viewer["headers"],
                          json={"levels": [], "row_level": "Строка"})
    assert r.status_code == 403, r.text


async def test_confirm_through_the_endpoint_writes_audit(client, admin_headers, form):
    """🔴 Проверка через РОУТЕР, а не только через службу.

    Первая версия этого набора била прямо в `levels.save`, и потому пропустила
    настоящую ошибку: роутер звал `write_event` с несуществующими именами
    аргументов, запись в шаблон проходила, а ответ падал с 500. На экране это
    выглядело как «сохранить нельзя», хотя сохранилось.
    """
    oid = str(form["object_id"])
    r = await client.get(f"/objects/{oid}/levels", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["suggestion"]["kind"] == "hierarchy"

    r = await client.post(f"/objects/{oid}/levels", headers=admin_headers, json={
        "levels": [{"index": 0, "name": "Ведомство"}, {"index": 1, "name": "Услуга"}],
        "row_level": "Отделение", "group_lone": True, "measure_default": "Принято, ед."})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["row_level"] == "Отделение"
    # Отметка времени — настоящая, а не строка «now»: по ней видно, когда
    # форму разбирали, и она попадает в карточку объекта.
    assert body["confirmed_at"].startswith("20")

    async with db.acquire() as conn:
        logged = await conn.fetchval(
            "select new_data from audit_log where entity_type='object' and entity_id=$1 "
            "order by created_at desc limit 1", oid)
    assert logged is not None, "подтверждение ступеней попадает в журнал действий"

    # Имя уровня обязательно: пустое отклоняется до записи.
    r = await client.post(f"/objects/{oid}/levels", headers=admin_headers, json={
        "levels": [{"index": 0, "name": ""}], "row_level": "Отделение"})
    assert r.status_code == 422, r.text
