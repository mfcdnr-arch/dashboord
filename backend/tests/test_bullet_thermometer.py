"""Два новых вида: «полосы план-факт» и «термометр к сроку».

**Полосы** отвечают на вопрос, которого не давали три отдельные карточки
«План-факт»: КТО из показателей отстаёт. Шкала у всех строк общая (100 % — это
план), и ровно поэтому показатели разного масштаба становятся сравнимыми —
чего в трёх карточках с разными осями не увидеть.

**Термометр** отвечает не на «сколько накоплено» (это «План-факт»), а на
«обгоняет ли темп календарь». У заказчика планы заданы сроком («до 1 сентября
2026 г.»), и до сих пор ответ считали в уме, сопоставляя проценты с датой.

Главное, что здесь проверяется, — не «сработало», а границы: где виджет
обязан МОЛЧАТЬ (один показатель, неразобранный срок) и где обязан сказать
правду вместо красивой картинки (перевыполнение на 656 %, несопоставимые
разрезы).
"""
from datetime import date

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from app.modules.dashboards import _suggest
from app.modules.dashboards._suggest import bullet_height, deadline_from_name

# Имена столбцов в том виде, в каком они приходят из госформы:
# «Показатель · Роль · Разрез». Срок в имени плана — настоящий, из формы МАХ.
PLAN_A = "Уведомления доставлены · План (до 1 сентября 2026 г.) · нарастающим итогом"
FACT_A = "Уведомления доставлены · Факт · нарастающим итогом"
PLAN_B = "Записались через МАХ · План (до 1 сентября 2026 г.) · нарастающим итогом"
FACT_B = "Записались через МАХ · Факт · нарастающим итогом"


def _pair_fields():
    return [{"code": "plan", "name": PLAN_A}, {"code": "fact", "name": FACT_A}]


def _two_pair_fields():
    return _pair_fields() + [{"code": "plan2", "name": PLAN_B}, {"code": "fact2", "name": FACT_B}]


def _ds(fields, **kw):
    base = {"code": "t", "name": "Форма", "periods": 2, "releases": 2,
            "fields": fields, "period_dates": ["2026-08-12", "2026-08-19"]}
    base.update(kw)
    return [base]


async def _page(client, headers, name):
    did = (await client.post("/dashboards", headers=headers, json={"name": name})).json()["id"]
    pid = (await client.post(f"/dashboards/{did}/pages", headers=headers,
                             json={"name": "Стр"})).json()["id"]
    return did, pid


async def _cleanup(did):
    async with db.acquire() as conn:
        await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
        await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
        await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
        await conn.execute("delete from dashboards where id=$1::uuid", did)


async def _data(client, headers, pid, body):
    r = await client.post(f"/dashboard-pages/{pid}/widgets", headers=headers, json=body)
    assert r.status_code == 201, r.text
    return (await client.get(f"/widgets/{r.json()['id']}/data", headers=headers)).json()


# ── Полосы ──────────────────────────────────────────────────────────────────

def test_bullet_replaces_separate_plan_fact_cards():
    """Несколько пар — одна карточка полос ВМЕСТО нескольких «План-фактов».

    Именно ради этого виджет и заводился: три пары занимали три карточки, где
    имя показателя весит больше числа, а сравнить их между собой нельзя вовсе.
    """
    specs = _suggest.plan_auto_build(_ds(_two_pair_fields()), None)
    kinds = [s["widget_type"] for s in specs]
    assert "bullet" in kinds, "при двух парах должны появиться полосы"
    assert "plan_fact" not in kinds, \
        "полосы и отдельные «План-факты» рядом — это дважды один и тот же ответ"

    bullet = next(s for s in specs if s["widget_type"] == "bullet")
    pairs = bullet["config"]["pairs"]
    assert [(p["plan_field"], p["fact_field"]) for p in pairs] == [("plan", "fact"), ("plan2", "fact2")]
    # Норма известна (100 % — сам план), поэтому пороги ставятся сразу: без них
    # полосы светят одним цветом, то есть выглядят сломанными.
    assert [r["level"] for r in bullet["config"]["alerts"]] == ["danger", "warn", "good"]


def test_single_pair_stays_a_plan_fact_card():
    """На ОДНОЙ паре полоса — это тот же «План-факт», только без прогноза.

    Сравнивать не с чем, а ради сравнения полосы и берут.
    """
    kinds = [s["widget_type"] for s in _suggest.plan_auto_build(_ds(_pair_fields()), None)]
    assert "plan_fact" in kinds and "bullet" not in kinds


def test_bullet_height_grows_with_rows_and_fit_layout_agrees():
    """Высота считается по числу пар — и «↕ Подогнать размеры» её не ломает.

    Ровно этот дефект уже ловили у матрицы: сборка растягивала виджет по
    содержимому, а подгонка тут же ужимала его до табличного размера, пряча
    строки во внутреннюю прокрутку.
    """
    assert bullet_height(2) < bullet_height(6), "шесть пар не помещаются в высоту двух"
    spec = next(s for s in _suggest.plan_auto_build(_ds(_two_pair_fields()), None)
                if s["widget_type"] == "bullet")
    assert spec["height"] == bullet_height(2)

    fitted = _suggest.fit_layout([{"id": "00000000-0000-0000-0000-000000000001",
                                   "widget_type": "bullet",
                                   "config": {"pairs": [{}] * 6}}])
    assert fitted[0]["height"] == bullet_height(6), \
        "подгонка обязана считать высоту тем же правилом, что и сборка"


async def test_bullet_compares_indicators_on_one_scale(client, admin_headers, seed_dataset):
    """Проценты, общая шкала и честная пометка обрезанной полосы.

    План 180 / факт 173 → 96,1 %. Вторая строка задана наоборот (план = факт
    как «план», факт = план) и даёт 104 % — так проверяется, что каждая строка
    считается сама по себе, а не делится на общий знаменатель.
    """
    did, pid = await _page(client, admin_headers, "ztest_bullet")
    try:
        d = await _data(client, admin_headers, pid, {
            "name": "Полосы", "widget_type": "bullet",
            "config": {"dataset_code": seed_dataset["code"],
                       "pairs": [{"plan_field": "plan", "fact_field": "fact"},
                                 {"plan_field": "fact", "fact_field": "plan", "label": "Наоборот"}]}})
        assert d["type"] == "bullet" and len(d["rows"]) == 2
        first, second = d["rows"]
        assert round(first["pct"], 1) == 96.1
        assert round(second["pct"], 1) == 104.0
        assert second["label"] == "Наоборот", "подпись строки задаётся человеком"
        # Шкала не ниже 120 %: иначе выполненный план упирается в самый край и
        # «выполнено» неотличимо от «перевыполнено».
        assert d["scale_max"] >= 120
        assert not any(r["clipped"] for r in d["rows"])
    finally:
        await _cleanup(did)


async def test_bullet_scale_does_not_let_one_row_crush_the_rest(client, admin_headers, seed_dataset):
    """🔴 Перевыполнение на сотни процентов не должно схлопывать остальные строки.

    У заказчика выполнение плана доходит до 656 %. Если тянуть шкалу за таким
    показателем, полосы остальных превращаются в невидимые огрызки — то есть
    виджет перестаёт отвечать на свой единственный вопрос. Потолок шкалы
    ограничен, а обрезанная полоса помечена: само число печатается всегда,
    поэтому из виду ничего не пропадает.
    """
    did, pid = await _page(client, admin_headers, "ztest_bullet_clip")
    try:
        async with db.acquire() as conn:
            rel = await conn.fetchval(
                "select id from dataset_releases where code=$1 and status<>'superseded' "
                "order by reporting_period_start desc limit 1", seed_dataset["code"])
            # Крошечный «план» рядом с обычным фактом даёт выполнение в тысячи
            # процентов — ровно тот случай, ради которого потолок и введён.
            await conn.execute(
                "insert into dataset_values(dataset_release_id,row_index,row_label,"
                "canonical_field_code,value_number) values($1,0,'Паспорт','tiny_plan',1)", rel)
        d = await _data(client, admin_headers, pid, {
            "name": "Полосы", "widget_type": "bullet",
            "config": {"dataset_code": seed_dataset["code"],
                       "pairs": [{"plan_field": "plan", "fact_field": "fact"},
                                 {"plan_field": "tiny_plan", "fact_field": "fact"}]}})
        assert d["scale_max"] <= 300, "шкалу не должен задирать один перевыполнивший"
        assert d["rows"][1]["clipped"] is True, "обрезанную полосу обязаны пометить"
        assert d["rows"][1]["pct"] > 1000, "само число при этом не теряется"
        assert d["rows"][0]["clipped"] is False
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from dataset_values where canonical_field_code='tiny_plan'")
        await _cleanup(did)


# ── Термометр ───────────────────────────────────────────────────────────────

def test_deadline_is_read_from_the_plan_column_name():
    """Срок берём из имени графы — он там уже написан, спрашивать его незачем."""
    assert deadline_from_name(PLAN_A) == date(2026, 9, 1)
    assert deadline_from_name("План (до 01.09.2026)") == date(2026, 9, 1)
    assert deadline_from_name("Показатель · План · к 31.12.2026") == date(2026, 12, 31)
    # «март» не должен становиться «маем»: ключи месяцев различаются с первых
    # букв, и порядок проверки это учитывает.
    assert deadline_from_name("План до 10 марта 2027 г.") == date(2027, 3, 10)
    assert deadline_from_name("План до 10 мая 2027 г.") == date(2027, 5, 10)


def test_no_deadline_no_thermometer():
    """Правило либо срабатывает уверенно, либо молчит.

    Выдуманный срок здесь хуже отсутствующего: по нему считается
    «опережение/отставание», и ошибка в дате превращается в ложную тревогу на
    первом экране руководителя.
    """
    assert deadline_from_name("Количество услуг · План · нарастающим итогом") is None
    assert deadline_from_name("до 40 сентября 2026") is None, "несуществующая дата — не дата"
    assert deadline_from_name("") is None

    plain = [{"code": "plan", "name": "Количество услуг · План · нарастающим итогом"},
             {"code": "fact", "name": "Количество услуг · Факт · нарастающим итогом"}]
    kinds = [s["widget_type"] for s in _suggest.plan_auto_build(_ds(plain), None)]
    assert "thermometer" not in kinds

    with_due = [s["widget_type"] for s in _suggest.plan_auto_build(_ds(_pair_fields()), None)]
    assert "thermometer" in with_due, "а когда срок назван — термометр нужен"


async def test_thermometer_compares_progress_with_the_calendar(client, admin_headers, seed_dataset):
    """Опережение считается в ПУНКТАХ, и «нужно в день» отвечает на «успеем ли».

    Отсчёт идёт от первого отчёта формы (01.01.2026) до срока; данные — на дату
    последнего отчёта (01.02.2026). Выполнено 96,1 % при прошедших 8,5 % срока,
    то есть опережение — и это должно быть сказано словами, а не оставлено
    читателю для вычитания процентов в уме.
    """
    did, pid = await _page(client, admin_headers, "ztest_therm")
    try:
        d = await _data(client, admin_headers, pid, {
            "name": "Термометр", "widget_type": "thermometer",
            "config": {"dataset_code": seed_dataset["code"], "plan_field": "plan",
                       "fact_field": "fact", "deadline": "2026-12-31"}})
        assert d["type"] == "thermometer"
        assert round(d["pct"], 1) == 96.1
        assert d["deadline"] == "2026-12-31"
        # Начало отсчёта не выдумано: это дата ПЕРВОГО отчёта формы. Возьми мы
        # «начало года» наугад — «прошло срока» стало бы неправдой.
        assert d["start"] == "2026-01-01" and d["as_of"] == "2026-02-01"
        assert d["days_total"] == 364 and d["days_left"] == 333
        assert round(d["elapsed_pct"], 1) == 8.5
        assert round(d["lead_pp"], 1) == round(d["pct"] - d["elapsed_pct"], 1)
        assert d["lead_pp"] > 0, "выполнено больше, чем прошло срока — это опережение"
        # Осталось 7 единиц из 180 на 333 дня.
        assert round(d["need_per_day"], 4) == round(7 / 333, 4)
    finally:
        await _cleanup(did)


async def test_thermometer_without_deadline_says_so(client, admin_headers, seed_dataset):
    """Без срока виджет не считается — и объясняет почему, а не молчит пустотой."""
    did, pid = await _page(client, admin_headers, "ztest_therm_nodue")
    try:
        r = await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "Термометр", "widget_type": "thermometer",
            "config": {"dataset_code": seed_dataset["code"],
                       "plan_field": "plan", "fact_field": "fact"}})
        data = await client.get(f"/widgets/{r.json()['id']}/data", headers=admin_headers)
        assert data.status_code == 400
        assert "срок" in data.json()["detail"].lower()
    finally:
        await _cleanup(did)


async def test_thermometer_reuses_the_same_forecast_as_plan_fact(client, admin_headers, seed_dataset):
    """Прогноз — ТОТ ЖЕ, что у «План-факта».

    Два расчёта «когда успеем» рядом однажды дали бы две разные даты на одном
    экране, и спорить пришлось бы уже о них, а не о данных.
    """
    did, pid = await _page(client, admin_headers, "ztest_therm_fc")
    try:
        therm = await _data(client, admin_headers, pid, {
            "name": "Термометр", "widget_type": "thermometer",
            "config": {"dataset_code": seed_dataset["code"], "plan_field": "plan",
                       "fact_field": "fact", "deadline": "2026-12-31"}})
        pf = await _data(client, admin_headers, pid, {
            "name": "План-факт", "widget_type": "plan_fact",
            "config": {"dataset_code": seed_dataset["code"], "plan_field": "plan",
                       "fact_field": "fact", "forecast": True}})
        assert therm["forecast"] == pf["forecast"]
    finally:
        await _cleanup(did)
