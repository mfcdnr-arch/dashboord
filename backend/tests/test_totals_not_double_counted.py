"""Итог не складывается со своими частями: сводная таблица и месячный бакет.

Правило в системе было, но жило в трёх местах и до этих двух не доехало:
проверка качества «итоговая графа против суммы составляющих», виджет
«Показатели списком» и сверка итоговой строки. Здесь закрываются оставшиеся.

Числа во всех проверках — НАСТОЯЩИЕ, снятые с дев-стенда: отчёт РЦО за
31.08.2026 («ИТОГО · Принято» 5 426, «ЕСИА · Принято» 2 885, «Росреестр ·
регистрация прав · Принято» 441) и три августовских отчёта формы МАХ по графе
«нарастающим итогом» (876 479 / 911 538 / 943 442). Синтетика тут была бы
слабее: правило целиком про то, как устроены реальные госформы.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from app.modules.dashboards._suggest import by_meaning_specs
from app.modules.dashboards._widgetcalc import _month_buckets

CODE = "ztd_ds"

# Две строки-отделения; суммы по строкам дают ровно числа отчёта за 31.08.2026.
FIELDS = {
    "itogo_acc": ("ИТОГО · Принято, ед.", {"Горловка": 3000.0, "Донецк": 2426.0}),
    "esia_acc": ("ЕСИА (260) · Принято, ед.", {"Горловка": 1600.0, "Донецк": 1285.0}),
    "rr_acc": ("Росреестр · Государственная регистрация прав · Принято, ед.",
               {"Горловка": 241.0, "Донецк": 200.0}),
    "itogo_iss": ("ИТОГО · Выдано, ед.", {"Горловка": 2500.0, "Донецк": 2000.0}),
    "esia_iss": ("ЕСИА (260) · Выдано, ед.", {"Горловка": 1400.0, "Донецк": 1100.0}),
    "share": ("Доля обращений через ЕСИА, %", {"Горловка": 60.0, "Донецк": 40.0}),
    # Форма, которая своего устройства не называет: разделителя « · » в имени нет.
    "plain_a": ("Количество рабочих часов", {"Горловка": 8.0, "Донецк": 9.0}),
    "plain_b": ("Количество работающих окон", {"Горловка": 4.0, "Донецк": 5.0}),
}


@pytest.fixture
async def td_ds(ids):
    async with db.acquire() as conn:
        await conn.execute("delete from dataset_values where dataset_release_id in "
                           "(select id from dataset_releases where code=$1)", CODE)
        await conn.execute("delete from dataset_releases where code=$1", CODE)
        await conn.execute("delete from objects where name=$1 and organization_id=$2",
                           "ztd_obj", ids["org"])
        obj = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,'ztd_obj') returning id", ids["org"])
        for code, (name, _v) in FIELDS.items():
            await conn.execute("insert into canonical_fields(object_id,code,name,data_type) "
                               "values($1,$2,$3,'number')", obj, code, name)
        rel = await conn.fetchval(
            "insert into dataset_releases(organization_id,code,name,status,"
            "reporting_period_start,created_by,object_id) "
            "values($1,$2,'Сводная',$3,$4::text::date,$5,$6) returning id",
            ids["org"], CODE, "released", "2026-08-31", ids["admin"], obj)
        for code, (_n, vals) in FIELDS.items():
            await conn.execute("insert into dataset_release_fields(dataset_release_id,"
                               "canonical_field_code) values($1,$2)", rel, code)
            for ri, (label, v) in enumerate(vals.items()):
                await conn.execute(
                    "insert into dataset_values(dataset_release_id,row_index,row_label,"
                    "canonical_field_code,value_number) values($1,$2,$3,$4,$5)",
                    rel, ri, label, code, v)
    yield CODE
    async with db.acquire() as conn:
        await conn.execute("delete from dataset_values where dataset_release_id in "
                           "(select id from dataset_releases where code=$1)", CODE)
        await conn.execute("delete from dataset_release_fields where dataset_release_id in "
                           "(select id from dataset_releases where code=$1)", CODE)
        await conn.execute("delete from dataset_releases where code=$1", CODE)
        await conn.execute("delete from canonical_fields where object_id in "
                           "(select id from objects where name='ztd_obj')")
        await conn.execute("delete from objects where name='ztd_obj'")


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


async def _pivot(client, headers, pid, fields):
    r = await client.post(f"/dashboard-pages/{pid}/widgets", headers=headers,
                          json={"name": "Сводная", "widget_type": "pivot",
                                "config": {"dataset_code": CODE, "value_fields": fields}})
    assert r.status_code == 201, r.text
    wid = r.json()["id"]
    return wid, (await client.get(f"/widgets/{wid}/data", headers=headers)).json()


async def test_total_column_is_not_added_to_its_own_parts(client, admin_headers, td_ds):
    """🔴 Свод не входит в сумму строки — иначе обращение считается дважды.

    Настоящие числа отчёта за 31.08.2026: было 5 426 + 2 885 + 441 = 8 752,
    правда — 5 426. Свод при этом никуда не пропадает: он показан своей графой
    и помечен, чтобы человек видел, ЧТО именно исключено из суммы.
    """
    did, pid = await _page(client, admin_headers, "ztd_total")
    try:
        _wid, d = await _pivot(client, admin_headers, pid, ["itogo_acc", "esia_acc", "rr_acc"])
        by_row = {r["row"]: r for r in d["rows"]}
        # Горловка: 1 600 + 241 = 1 841, а не 1 600 + 241 + 3 000.
        assert by_row["Горловка"]["total"] == 1841.0
        assert by_row["Донецк"]["total"] == 1485.0
        assert d["grand_total"] == 3326.0          # 2 885 + 441, а не 8 752
        assert d["total_columns"] == [0]           # свод найден и назван
        assert d["row_total"] is True
        # Сама графа-свод осталась в таблице со своим значением.
        assert d["col_totals"][0] == 5426.0
        assert "свод" in d["total_note"]
    finally:
        await _cleanup(did)


async def test_no_row_total_when_columns_measure_different_things(client, admin_headers, td_ds):
    """«Принято» и «Выдано» — стадии одного обращения, итога по строке нет вовсе.

    Тот же выбор, что у «Показателей списком», где по той же причине не
    показывается доля: пустая колонка читалась бы как поломка, поэтому итога
    нет, а причина названа словами.
    """
    did, pid = await _page(client, admin_headers, "ztd_mixed")
    try:
        # Обе графы — составляющие: свод здесь ни при чём, спор именно о том,
        # что «Принято» и «Выдано» нельзя складывать между собой.
        _wid, d = await _pivot(client, admin_headers, pid, ["esia_acc", "esia_iss"])
        assert d["row_total"] is False
        assert all(r["total"] is None for r in d["rows"])
        assert d["grand_total"] is None
        assert "разные показатели" in d["total_note"]
        assert "Принято, ед." in d["total_note"] and "Выдано, ед." in d["total_note"]
    finally:
        await _cleanup(did)


async def test_share_column_is_averaged_and_kept_out_of_the_sum(client, admin_headers, td_ds):
    """Доля не складывается: в сумму не входит, а её итог по столбцу — среднее."""
    did, pid = await _page(client, admin_headers, "ztd_share")
    try:
        _wid, d = await _pivot(client, admin_headers, pid, ["esia_acc", "rr_acc", "share"])
        by_row = {r["row"]: r for r in d["rows"]}
        assert by_row["Горловка"]["total"] == 1841.0        # 60 % не прибавились
        assert d["share_columns"] == [2]
        assert d["col_aggregate"] == ["sum", "sum", "avg"]
        assert d["col_totals"][2] == 50.0                   # среднее 60 и 40, а не 100
        assert "Доли" in d["total_note"]
    finally:
        await _cleanup(did)


async def test_form_without_separator_keeps_the_old_behaviour(client, admin_headers, td_ds):
    """Форма не назвала своего устройства — правило молчит, а не гадает.

    Та же оговорка, что в проверке качества: без « · » в именах неизвестно,
    какие графы складываются, и запрет был бы выдумкой в другую сторону.
    """
    did, pid = await _page(client, admin_headers, "ztd_plain")
    try:
        _wid, d = await _pivot(client, admin_headers, pid, ["plain_a", "plain_b"])
        by_row = {r["row"]: r for r in d["rows"]}
        assert d["row_total"] is True
        assert by_row["Горловка"]["total"] == 12.0
        assert d["total_note"] is None
    finally:
        await _cleanup(did)


# ── Месяц из отчётов ────────────────────────────────────────────────────────

MAX_AUG = [("2026-08-05", 876479.0), ("2026-08-12", 911538.0), ("2026-08-19", 943442.0)]


def test_cumulative_month_is_the_last_report_not_the_sum():
    """🔴 Накопительный итог месяца — последний отчёт, а не сумма отчётов.

    Настоящие числа формы МАХ: сумма даёт 2 731 459 — в 2,9 раза больше правды
    (943 442) и в 28,5 раза больше месячного прироста. Раньше месяц собирался
    плюсом при любом показателе.
    """
    vmap, fold, reports = _month_buckets(
        [("2026-07-22", 847714.0)] + MAX_AUG,
        "Количество успешно доставленных уведомлений · Факт · нарастающим итогом**")
    assert fold == "last"
    assert vmap["2026-08"] == 943442.0
    assert vmap["2026-07"] == 847714.0
    # Число отчётов месяца возвращается всегда: месяцы неравны между собой.
    assert reports == {"2026-07": 1, "2026-08": 3}


def test_flow_is_summed_and_share_is_averaged():
    """Поток за период складывается, доля усредняется — правило одно на систему."""
    flow, fold_flow, _ = _month_buckets(MAX_AUG, "ИТОГО · Принято, ед.")
    assert fold_flow == "sum"
    assert flow["2026-08"] == 876479.0 + 911538.0 + 943442.0

    share, fold_share, _ = _month_buckets(
        [("2026-08-05", 30.0), ("2026-08-12", 40.0), ("2026-08-19", 50.0)],
        "Доля доставленных, %")
    assert fold_share == "avg"
    assert share["2026-08"] == 40.0


def test_reports_per_month_are_counted_for_uneven_months():
    """Июль 27 отчётов против августа 26 — без этой цифры сравнение вводит в заблуждение.

    Замер на РЦО: голая разница месяцев даёт −3,1 % («просели»), а на один
    отчёт +0,6 % («выросли») — знак переворачивается.
    """
    pairs = ([(f"2026-07-{d:02d}", 4065.0) for d in range(1, 28)]
             + [(f"2026-08-{d:02d}", 4090.0) for d in range(1, 27)])
    vmap, fold, reports = _month_buckets(pairs, "ИТОГО · Принято, ед.")
    assert fold == "sum"
    assert reports == {"2026-07": 27, "2026-08": 26}
    assert vmap["2026-07"] > vmap["2026-08"]                       # месяц в целом просел
    assert vmap["2026-07"] / 27 < vmap["2026-08"] / 26             # а на отчёт — вырос


def test_heatmap_does_not_mix_the_total_with_its_parts():
    """Тепловая карта: клетка свода СОДЕРЖИТ клетку части, сравнивать их нельзя.

    Отбор идёт по объёму, а самый объёмный — всегда свод, поэтому раньше он
    попадал в карту первым (на дашборде заказчика — оба свода сразу).
    """
    fields = [{"code": "itogo_acc", "name": "ИТОГО · Принято, ед."},
              {"code": "itogo_iss", "name": "ИТОГО · Выдано, ед."},
              {"code": "esia_acc", "name": "ЕСИА (260) · Принято, ед."},
              {"code": "rr_acc", "name": "Росреестр · Регистрация прав · Принято, ед."},
              {"code": "zags_acc", "name": "ЗАГС (377) · Принято, ед."}]
    volumes = {"itogo_acc": 5426.0, "itogo_iss": 4500.0,
               "esia_acc": 2885.0, "rr_acc": 441.0, "zags_acc": 300.0}
    specs = by_meaning_specs(fields, rows=63, periods=54, volumes=volumes)
    heat = [s for s in specs if s["kind"] == "heatmap"]
    assert heat, "тепловая карта должна предлагаться на такой форме"
    names = [f["name"] for f in heat[0]["fields"]]
    assert not any("ИТОГО" in n for n in names)
    assert "ЕСИА (260) · Принято, ед." in names


def test_heatmap_keeps_totals_when_there_is_nothing_else():
    """А если в форме одни своды — брать больше нечего, карта остаётся прежней."""
    fields = [{"code": "a", "name": "ИТОГО · Принято, ед."},
              {"code": "b", "name": "ИТОГО · Выдано, ед."}]
    specs = by_meaning_specs(fields, rows=63, periods=54,
                             volumes={"a": 5426.0, "b": 4500.0})
    heat = [s for s in specs if s["kind"] == "heatmap"]
    assert heat and len(heat[0]["fields"]) == 2
