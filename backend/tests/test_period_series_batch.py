"""Ряд по периодам не должен стоить запроса на каждый отчёт.

Замер на живых данных: страница «Обзор» дашборда РЦО тянула **3026 запросов**
к базе, из них **3816 выполнений** одного и того же «сумма по одному выпуску» —
он звался в цикле по всем 54 выпускам, и так для каждого показателя каждого
виджета. Само по себе это быстро (доли миллисекунды), но тысячи обращений в
одном ответе — это задержка и нагрузка, растущие вместе с историей: через год
отчётов станет вдвое больше, и цена вырастет линейно.

Приём тот же, что уже применён в матрице «строка × отчёт»: один запрос
`= any($1::uuid[])` с группировкой.
"""
from __future__ import annotations

import uuid

import pytest

from app import db
from app.modules.dashboards import _widgetsources as ws

pytestmark = pytest.mark.asyncio(loop_scope="session")

CODE = "ztest_ps"
FIELD = "ztest_plan"


class CountingConn:
    """Прокси над соединением, считающий обращения к базе.

    Нужен, чтобы «стало быстрее» проверялось числом запросов, а не секундомером:
    время на стенде скачет от посторонней нагрузки, а число обращений — факт.
    """

    def __init__(self, conn):
        self._conn = conn
        self.calls = 0

    def __getattr__(self, name):
        attr = getattr(self._conn, name)
        if name in ("fetch", "fetchval", "fetchrow", "execute"):
            async def counted(*a, **kw):
                self.calls += 1
                return await attr(*a, **kw)
            return counted
        return attr


@pytest.fixture
async def series_data(ids):
    """Четыре выпуска одного датасета; в ТРЕТЬЕМ нужного поля нет вовсе."""
    async with db.acquire() as conn:
        obj = await conn.fetchval(
            "insert into objects(organization_id, name, code) values($1,$2,$3) returning id",
            ids["org"], f"ztest_ps_obj_{uuid.uuid4().hex[:6]}", f"ztest_ps_{uuid.uuid4().hex[:6]}")
        rels = []
        for i, day in enumerate(("2026-01-01", "2026-01-08", "2026-01-15", "2026-01-22")):
            rid = await conn.fetchval(
                "insert into dataset_releases(organization_id, object_id, code, name, "
                "reporting_period_start, status, created_by) "
                "values($1,$2,$3,$4,$5::text::date,'released',$6) returning id",
                ids["org"], obj, CODE, f"Выпуск {i}", day, ids["admin"])
            rels.append(rid)
            if i == 2:
                continue  # отчёт пришёл, но этого показателя в нём нет
            for j, (label, val) in enumerate((("Донецк", 100 + i), ("Макеевка", 200 + i))):
                await conn.execute(
                    "insert into dataset_values(dataset_release_id, row_index, row_label, "
                    "canonical_field_code, value_number) values($1,$2,$3,$4,$5)",
                    rid, j, label, FIELD, val)
        yield {"org": ids["org"], "object": obj, "releases": rels}
        await conn.execute("delete from dataset_values where dataset_release_id = any($1::uuid[])", rels)
        await conn.execute("delete from dataset_releases where id = any($1::uuid[])", rels)
        await conn.execute("delete from objects where id=$1", obj)


async def test_ryad_schitaetsya_odnim_zaprosom_na_vse_otchety(series_data):
    """🔴 Главное: число обращений к базе не растёт с числом отчётов.

    Было — запрос на каждый выпуск (у РЦО их 54, и так на каждый показатель
    каждого виджета). Стало — список выпусков плюс один запрос значений.
    """
    async with db.acquire() as raw:
        conn = CountingConn(raw)
        out = await ws._dataset_period_series(conn, series_data["org"], CODE, FIELD)
        assert conn.calls <= 2, f"на 4 отчёта ушло {conn.calls} обращений к базе — ряд снова считается по одному"
        assert len(out) == 4, out


async def test_otchet_bez_pokazatelya_ostaetsya_tochkoy_ryada(series_data):
    """🔴 Отчёт пришёл, а показателя в нём нет — это ноль, а не пропуск.

    При группировке такой выпуск не попадает в результат вовсе, и точка молча
    исчезла бы из графика: ряд стал бы короче, а «Динамика» показала бы
    непрерывный рост там, где на самом деле был провал.
    """
    async with db.acquire() as raw:
        out = await ws._dataset_period_series(raw, series_data["org"], CODE, FIELD)
    assert [p for p, _ in out] == ["2026-01-01", "2026-01-08", "2026-01-15", "2026-01-22"], out
    assert out[2][1] == 0.0, f"выпуск без показателя должен давать 0, а не пропадать: {out}"


async def test_summy_sovpadayut_s_dannymi(series_data):
    """Числа не должны измениться от способа запроса."""
    async with db.acquire() as raw:
        out = await ws._dataset_period_series(raw, series_data["org"], CODE, FIELD)
    assert out[0][1] == 300.0, out   # 100 + 200
    assert out[1][1] == 302.0, out   # 101 + 201
    assert out[3][1] == 306.0, out   # 103 + 203


async def test_filtr_stroki_rabotaet_kak_prezhde(series_data):
    async with db.acquire() as raw:
        out = await ws._dataset_period_series(raw, series_data["org"], CODE, FIELD, row="Донецк")
    assert [v for _, v in out] == [100.0, 101.0, 0.0, 103.0], out


async def test_prava_na_stroki_uvazhayutsya(series_data):
    """Сужение по разрешённым строкам не должно потеряться при пакетном запросе."""
    async with db.acquire() as raw:
        out = await ws._dataset_period_series(raw, series_data["org"], CODE, FIELD, allowed={"Макеевка"})
    assert [v for _, v in out] == [200.0, 201.0, 0.0, 203.0], out


async def test_period_szhivaet_ryad(series_data):
    async with db.acquire() as raw:
        out = await ws._dataset_period_series(raw, series_data["org"], CODE, FIELD,
                                              from_date="2026-01-08", to_date="2026-01-15")
    assert [p for p, _ in out] == ["2026-01-08", "2026-01-15"], out
