"""«Год к году» собирает месяц по смыслу графы (ревью этапа 2, 29.09.2026).

Было: месяц складывался плюсом при любом показателе. На нарастающем итоге
формы МАХ август давал 2 731 459 вместо 943 442 — сумма трёх накопительных
значений, числа, которого не существует. Вид ставится как раз на главный
разрез («нарастающим итогом»), поэтому дефект проявился бы на первом же
переходе истории через границу года.
"""
import uuid

import pytest

from app import db

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _seed(ids, name, points):
    code = f"ztest_yoy_{uuid.uuid4().hex[:6]}"
    async with db.acquire() as conn:
        obj = await conn.fetchval(
            "insert into objects(organization_id, name, code) values($1,$2,$3) returning id",
            ids["org"], f"ztest_yoy_obj_{uuid.uuid4().hex[:6]}", code)
        await conn.execute(
            "insert into canonical_fields(object_id, code, name, data_type) values($1,'v',$2,'number')",
            obj, name)
        rels = []
        for day, val in points:
            rid = await conn.fetchval(
                "insert into dataset_releases(organization_id, object_id, code, name, "
                "reporting_period_start, status, created_by) "
                "values($1,$2,$3,$4,$5::text::date,'released',$6) returning id",
                ids["org"], obj, code, f"Выпуск {day}", day, ids["admin"])
            rels.append(rid)
            await conn.execute(
                "insert into dataset_values(dataset_release_id, row_index, row_label, "
                "canonical_field_code, value_number) values($1,0,'ДНР','v',$2)", rid, val)
    return code, obj, rels


async def _drop(obj, rels):
    async with db.acquire() as conn:
        await conn.execute("delete from dataset_values where dataset_release_id = any($1::uuid[])", rels)
        await conn.execute("delete from dataset_releases where id = any($1::uuid[])", rels)
        await conn.execute("delete from canonical_fields where object_id=$1", obj)
        await conn.execute("delete from objects where id=$1", obj)


async def _yoy(client, headers, code):
    r = await client.post("/widgets/preview", headers=headers, json={
        "widget_type": "yoy", "name": "ГкГ", "config": {"dataset_code": code, "value_field": "v"}})
    assert r.status_code == 200, r.text
    return r.json()


async def test_cumulative_month_is_its_last_report(client, admin_headers, ids):
    """Нарастающий итог: месяц — последний отчёт, сравнение — последний общий месяц."""
    # Два общих месяца: сумма месяцев и «последний общий месяц» тогда различаются.
    code, obj, rels = await _seed(ids, "Обращения · Факт · нарастающим итогом", [
        ("2025-07-30", 480_000),
        ("2025-08-06", 500_000), ("2025-08-13", 520_000), ("2025-08-20", 540_000),
        ("2026-07-29", 850_000),
        ("2026-08-05", 876_479), ("2026-08-12", 911_538), ("2026-08-19", 943_442),
    ])
    try:
        d = await _yoy(client, admin_headers, code)
        assert d["fold"] == "last"
        assert d["current"][7] == 943_442, "август — последний отчёт, а не сумма трёх"
        assert d["previous"][7] == 540_000
        assert d["compared_months"] == 2
        assert d["change"] == 943_442 - 540_000, "сравнивается последний общий месяц, а не сумма"
        assert d["current_total"] == 943_442, "итог накопительного — последнее значение"
        assert d["previous_total"] == 540_000
    finally:
        await _drop(obj, rels)


async def test_share_month_is_averaged(client, admin_headers, ids):
    """Доля усредняется по отчётам месяца, а не складывается."""
    code, obj, rels = await _seed(ids, "Доля доставленных, %", [
        ("2025-03-01", 60), ("2025-03-15", 80), ("2026-03-01", 70), ("2026-03-15", 90),
    ])
    try:
        d = await _yoy(client, admin_headers, code)
        assert d["fold"] == "avg"
        assert d["current"][2] == 80 and d["previous"][2] == 70
        assert d["change"] == 10
    finally:
        await _drop(obj, rels)


async def test_flow_month_is_still_summed(client, admin_headers, ids):
    """Поток за период складывается — как и было."""
    code, obj, rels = await _seed(ids, "Обращения · Факт · за отчетную неделю", [
        ("2025-05-05", 10), ("2025-05-12", 20), ("2026-05-04", 15), ("2026-05-11", 25),
    ])
    try:
        d = await _yoy(client, admin_headers, code)
        assert d["fold"] == "sum"
        assert d["current"][4] == 40 and d["previous"][4] == 30 and d["change"] == 10
    finally:
        await _drop(obj, rels)


async def test_pinned_series_stop_at_the_pinned_date(client, admin_headers, ids):
    """🔴 Снимок не показывает будущего: ряд закреплённого виджета обрывается на дате.

    До 29.09 это делали только мини-график и прирост карточки, а «Динамика»,
    матрица и «Год к году» на дашборде «по файлу за 22.07» росли с каждым новым
    файлом, хотя мастер обещал обратное.
    """
    code, obj, rels = await _seed(ids, "Обращения · Факт · за отчетную неделю", [
        ("2026-07-08", 10), ("2026-07-15", 20), ("2026-07-22", 30), ("2026-07-29", 40),
    ])
    try:
        cfg = {"dataset_code": code, "value_field": "v", "period": "2026-07-22"}
        r = await client.post("/widgets/preview", headers=admin_headers, json={
            "widget_type": "dynamics", "name": "Д", "config": cfg})
        assert r.status_code == 200, r.text
        d = r.json()
        periods = [p for p in d.get("categories") or d.get("periods") or []]
        assert periods and max(periods) <= "2026-07-22", f"срез показал будущее: {periods}"
        assert "2026-07-29" not in str(d), "отчёт после даты среза попал в ряд"

        free = (await client.post("/widgets/preview", headers=admin_headers, json={
            "widget_type": "dynamics", "name": "Д",
            "config": {"dataset_code": code, "value_field": "v"}})).json()
        assert "2026-07-29" in str(free), "без закрепления ряд по-прежнему полный"
    finally:
        await _drop(obj, rels)
