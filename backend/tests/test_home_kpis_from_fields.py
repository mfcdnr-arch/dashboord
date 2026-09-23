"""«Показатели формы → карточки на Главной» (home.service.add_kpis_from_fields):
мастер заводит метрику по рецепту сумма/среднее и сразу выносит на «Главную».

🔴 Регрессия 23.09.2026: единица измерения не передавалась вовсе (всегда
None) — процентное поле получало карточку с голым числом, а прирост считался
ОБЫЧНЫМ относительным (не в пунктах) — «80 % → 85 %» читалось бы как «+6,25 %»
вместо «+5 п.п.», то есть двусмысленно ровно там, где для этого и заведены
пункты (KpiDelta.tsx). Нашлось не тестом, а живым заведением метрик по
просьбе заказчика: у "% достижения показателя" на карточке не было "%".
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from app.modules.home import service as home_svc
from app.modules.metrics import service as metric_svc


async def _cleanup(org_id, actor, codes):
    async with db.acquire() as conn:
        for code in codes:
            await home_svc.remove_kpi(conn, org_id, code)
            m = await conn.fetchval(
                "select id from metrics where organization_id=$1 and code=$2", org_id, code)
            if m:
                await metric_svc.delete_metric(conn, org_id, actor, str(m))


@pytest.mark.asyncio(loop_scope="session")
async def test_percent_field_gets_percent_unit_and_average(ids, seed_dataset):
    org, actor = ids["org"], ids["admin"]
    async with db.acquire(actor_user_id=actor) as conn:
        result = await home_svc.add_kpis_from_fields(
            conn, org, actor, seed_dataset["code"],
            [{"field_code": "fact", "field_name": "Выполнение плана, %"}])
    code = result["created"][0]["code"]
    try:
        async with db.acquire() as conn:
            row = await conn.fetchrow(
                "select mv.unit, mv.formula_expression from metrics m "
                "join metric_versions mv on mv.metric_id=m.id "
                "where m.organization_id=$1 and m.code=$2", org, code)
        assert row["unit"] == "%", "поле со знаком % в имени обязано получить unit='%'"
        assert row["formula_expression"].startswith("AVG("), "доля/процент усредняется, а не складывается"
    finally:
        await _cleanup(org, actor, [code])


@pytest.mark.asyncio(loop_scope="session")
async def test_count_field_stays_without_unit_and_is_summed(ids, seed_dataset):
    org, actor = ids["org"], ids["admin"]
    async with db.acquire(actor_user_id=actor) as conn:
        result = await home_svc.add_kpis_from_fields(
            conn, org, actor, seed_dataset["code"],
            [{"field_code": "plan", "field_name": "Количество заявок, ед."}])
    code = result["created"][0]["code"]
    try:
        async with db.acquire() as conn:
            row = await conn.fetchrow(
                "select mv.unit, mv.formula_expression from metrics m "
                "join metric_versions mv on mv.metric_id=m.id "
                "where m.organization_id=$1 and m.code=$2", org, code)
        assert row["unit"] is None, "явная единица количества («, ед.») — не проценты"
        assert row["formula_expression"].startswith("SUM("), "количество складывается, а не усредняется"
    finally:
        await _cleanup(org, actor, [code])
