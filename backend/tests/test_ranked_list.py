"""Рейтинг строк: кто впереди и кто в хвосте.

Ни один из прежних видов на этот вопрос не отвечал. Столбчатый график на 63
отделения — частокол; светофор красит «где плохо», но порядка не выстраивает;
таблицу надо сортировать руками и читать числа подряд.

Главное, что здесь проверяется, — не «список отрисовался», а две вещи, в
которых рейтинг легко начинает врать: масштаб полос (антитоп нельзя рисовать
от СВОЕГО максимума — он выглядел бы вровень с топом) и честность разрыва
(«… ещё 0 строк …» между половинами показанного целиком списка).
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from app.modules.dashboards import _suggest
from app.modules.dashboards._suggest import ranked_height, ranked_rows_shown

# Двенадцать «отделений» с заведомо разным весом: первое в тридцать раз больше
# последнего — ровно тот разброс, на котором общий масштаб полос и виден.
OFFICES = [("Отделение %02d" % i, float(1200 - i * 100)) for i in range(1, 13)]
FIELD, PLAN_FIELD = "rank_val", "rank_plan"


async def _seed_rows(code: str):
    """Двенадцать строк в активном выпуске тестового датасета."""
    async with db.acquire() as conn:
        rel = await conn.fetchval(
            "select id from dataset_releases where code=$1 and status<>'superseded' "
            "order by reporting_period_start desc limit 1", code)
        for i, (label, value) in enumerate(OFFICES):
            await conn.execute(
                "insert into dataset_values(dataset_release_id,row_index,row_label,"
                "canonical_field_code,value_number) values($1,$2,$3,$4,$5)",
                rel, 100 + i, label, FIELD, value)
            # План НАОБОРОТ пропорционален: у крупных он больше, поэтому по
            # выполнению порядок обязан отличаться от порядка по величине.
            await conn.execute(
                "insert into dataset_values(dataset_release_id,row_index,row_label,"
                "canonical_field_code,value_number) values($1,$2,$3,$4,$5)",
                rel, 100 + i, label, PLAN_FIELD, value * (2.0 if i < 6 else 0.5))
    return rel


async def _drop_rows():
    async with db.acquire() as conn:
        await conn.execute("delete from dataset_values where canonical_field_code = any($1::text[])",
                           [FIELD, PLAN_FIELD])


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


async def _data(client, headers, pid, cfg, name="Рейтинг"):
    r = await client.post(f"/dashboard-pages/{pid}/widgets", headers=headers,
                          json={"name": name, "widget_type": "ranked", "config": cfg})
    assert r.status_code == 201, r.text
    return (await client.get(f"/widgets/{r.json()['id']}/data", headers=headers)).json()


async def test_top_and_bottom_with_an_honest_gap(client, admin_headers, seed_dataset):
    """Топ, антитоп и разрыв, который не врёт о числе пропущенных строк."""
    await _seed_rows(seed_dataset["code"])
    did, pid = await _page(client, admin_headers, "zrank_gap")
    try:
        d = await _data(client, admin_headers, pid,
                        {"dataset_code": seed_dataset["code"], "value_field": FIELD, "top_n": 3})
        assert d["type"] == "ranked"
        # Три сверху и три снизу: показано 6 из 12, пропущено ровно 6.
        assert [r["rank"] for r in d["rows"]] == [1, 2, 3, 10, 11, 12]
        assert d["skipped"] == 6 and d["rows_total"] == 12
        assert d["rows"][0]["label"] == "Отделение 01", "первым идёт крупнейший"
        assert d["rows"][-1]["label"] == "Отделение 12", "последним — хвост"
        # Доля в итоге отвечает на «насколько он весит»: первое место с 40 % и
        # первое место с 3 % — разные новости.
        assert sum(r["share"] for r in d["rows"]) < 100, "показана часть строк — и доля это часть"
    finally:
        await _cleanup(did)
        await _drop_rows()


async def test_bar_scale_is_taken_from_all_rows_not_shown_ones(client, admin_headers, seed_dataset):
    """🔴 Масштаб полос — по ВСЕМ строкам, иначе антитоп выглядит вровень с топом.

    Полосу рисует клиент от `scale_max`. Возьми сервер максимум по показанным
    строкам — хвост нарисовался бы во всю ширину карточки, то есть выглядел бы
    так же убедительно, как лидер. Та же ошибка, что уже чинили у полосок в
    ячейках таблицы.
    """
    await _seed_rows(seed_dataset["code"])
    did, pid = await _page(client, admin_headers, "zrank_scale")
    try:
        full = await _data(client, admin_headers, pid,
                           {"dataset_code": seed_dataset["code"], "value_field": FIELD, "top_n": 6})
        only_tail = await _data(client, admin_headers, pid,
                                {"dataset_code": seed_dataset["code"], "value_field": FIELD,
                                 "top_n": 3, "bottom": True}, name="Рейтинг 2")
        # В обоих случаях масштаб один и тот же — максимум по всей форме.
        assert full["scale_max"] == only_tail["scale_max"] == max(v for _, v in OFFICES)
    finally:
        await _cleanup(did)
        await _drop_rows()


async def test_no_gap_when_the_whole_list_is_shown(client, admin_headers, seed_dataset):
    """Разрыв в ноль строк — не разрыв, а обман: список и так показан целиком."""
    await _seed_rows(seed_dataset["code"])
    did, pid = await _page(client, admin_headers, "zrank_nogap")
    try:
        d = await _data(client, admin_headers, pid,
                        {"dataset_code": seed_dataset["code"], "value_field": FIELD, "top_n": 6})
        assert len(d["rows"]) == 12 and d["skipped"] == 0
        assert [r["rank"] for r in d["rows"]] == list(range(1, 13)), "места идут подряд"
    finally:
        await _cleanup(did)
        await _drop_rows()


async def test_ranking_by_plan_does_not_reward_size(client, admin_headers, seed_dataset):
    """Порядок по выполнению плана отличается от порядка по величине.

    В этом и смысл: по абсолютному числу крупное отделение выигрывает всегда, а
    по исполнению плана может оказаться в хвосте. План у крупных здесь вдвое
    больше значения (выполнение 50 %), у мелких — вдвое меньше (200 %).
    """
    await _seed_rows(seed_dataset["code"])
    did, pid = await _page(client, admin_headers, "zrank_plan")
    try:
        by_value = await _data(client, admin_headers, pid,
                               {"dataset_code": seed_dataset["code"], "value_field": FIELD, "top_n": 3})
        by_plan = await _data(client, admin_headers, pid,
                              {"dataset_code": seed_dataset["code"], "value_field": FIELD,
                               "plan_field": PLAN_FIELD, "rank_by": "plan_pct", "top_n": 3},
                              name="Рейтинг по плану")
        assert by_plan["rank_by"] == "plan_pct"
        assert by_value["rows"][0]["label"] == "Отделение 01", "по величине первый — крупнейший"
        # Крупнейшее отделение выполняет план на 50 % и в топ по исполнению не
        # попадает вовсе. Проверяем ГРУППУ, а не конкретное имя: у шести строк
        # выполнение ровно 50 %, и порядок между равными определяется
        # устойчивостью сортировки — привязываться к нему значило бы проверять
        # деталь реализации вместо правила.
        assert "Отделение 01" not in [r["label"] for r in by_plan["rows"][:3]]
        assert all(round(r["pct"]) == 200 for r in by_plan["rows"][:3]), "впереди — перевыполнившие"
        assert all(round(r["pct"]) == 50 for r in by_plan["rows"][-3:]), "в хвосте — отстающие"
    finally:
        await _cleanup(did)
        await _drop_rows()


async def test_rows_without_plan_are_not_pushed_to_the_tail(client, admin_headers, seed_dataset):
    """Строка без плана не участвует в рейтинге «по выполнению».

    Приписать ей ноль значило бы отправить её в хвост за то, что план ей просто
    не задан, — и антитоп заполнился бы строками, к которым претензий нет.
    """
    await _seed_rows(seed_dataset["code"])
    async with db.acquire() as conn:
        await conn.execute("delete from dataset_values where canonical_field_code=$1 "
                           "and row_label='Отделение 12'", PLAN_FIELD)
    did, pid = await _page(client, admin_headers, "zrank_noplan")
    try:
        d = await _data(client, admin_headers, pid,
                        {"dataset_code": seed_dataset["code"], "value_field": FIELD,
                         "plan_field": PLAN_FIELD, "rank_by": "plan_pct", "top_n": 6})
        labels = [r["label"] for r in d["rows"]]
        assert "Отделение 12" not in labels
        assert d["rows_total"] == 11, "строка без плана не считается и в итоге"
    finally:
        await _cleanup(did)
        await _drop_rows()


async def test_tied_last_place_is_named_not_faked(client, admin_headers, seed_dataset):
    """🔴 Порядок между равными строками — не рейтинг, и об этом надо сказать.

    Найдено на живых данных: в форме МВД у сорока пяти отделений значение 0, а
    список проставлял им места 58, 59, 60… Числа верны, но порядок между ними
    задан лишь устойчивостью сортировки — выдавать его за рейтинг нельзя.
    """
    await _seed_rows(seed_dataset["code"])
    async with db.acquire() as conn:
        rel = await conn.fetchval(
            "select id from dataset_releases where code=$1 and status<>'superseded' "
            "order by reporting_period_start desc limit 1", seed_dataset["code"])
        # Половина отделений обнуляется — так и выглядит его настоящая форма.
        await conn.execute("update dataset_values set value_number=0 "
                           "where dataset_release_id=$1 and canonical_field_code=$2 "
                           "and row_index >= 106", rel, FIELD)
    did, pid = await _page(client, admin_headers, "zrank_tied")
    try:
        d = await _data(client, admin_headers, pid,
                        {"dataset_code": seed_dataset["code"], "value_field": FIELD, "top_n": 2})
        assert d["tied_last"] == 6, "шесть строк делят последнее место"
        assert d["tied_value"] == 0

        # А когда равных нет, оговорка не нужна и не приходит: лишнее
        # предупреждение приучает пролистывать настоящие.
        await _drop_rows()
        await _seed_rows(seed_dataset["code"])
        clean = await _data(client, admin_headers, pid,
                            {"dataset_code": seed_dataset["code"], "value_field": FIELD, "top_n": 2},
                            name="Рейтинг без равных")
        assert clean["tied_last"] == 0
    finally:
        await _cleanup(did)
        await _drop_rows()


def test_height_follows_the_setting_and_fit_layout_agrees():
    """Высота — по числу показанных строк, и подгонка считает её тем же правилом.

    Ровно этот дефект уже ловили у матрицы и у полос: сборка растягивала виджет
    по содержимому, а кнопка «↕ Подогнать размеры» тут же ужимала его обратно,
    пряча строки во внутреннюю прокрутку.
    """
    assert ranked_rows_shown({}) == 10, "по умолчанию пять сверху и пять снизу"
    assert ranked_rows_shown({"top_n": 3}) == 6
    assert ranked_rows_shown({"top_n": 3, "bottom": False}) == 3
    assert ranked_height(6) < ranked_height(10)

    fitted = _suggest.fit_layout([{"id": "00000000-0000-0000-0000-000000000002",
                                   "widget_type": "ranked",
                                   "config": {"top_n": 5, "bottom": True}}])
    assert fitted[0]["height"] == ranked_height(10)


def test_auto_build_adds_ranking_only_when_rows_are_many():
    """Рейтинг появляется там, где строк слишком много, чтобы читать их подряд.

    На шести отделениях светофор уже отвечает «где плохо», и список повторил бы
    плитки; на шестидесяти трёх плитки превращаются в стену, и «кто в хвосте»
    из них не вычитывается.
    """
    fields = [{"code": "fact", "name": "Заявлений принято · Факт · нарастающим итогом"}]
    ds = lambda rows: [{"code": "t", "name": "Форма", "periods": 2, "releases": 2,  # noqa: E731
                        "fields": fields, "rows": rows, "period_dates": []}]
    few = [s["widget_type"] for s in _suggest.plan_auto_build(ds(6), None)]
    many = [s["widget_type"] for s in _suggest.plan_auto_build(ds(40), None)]
    assert "ranked" not in few and "status_grid" in few
    assert "ranked" in many, "на сорока отделениях порядок нужен"
