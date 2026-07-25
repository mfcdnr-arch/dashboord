"""Оконные функции формул на реальных данных (через /metrics/preview).
seed t_ds: поле plan по 2 периодам — суммы 165 (2026-01) и 180 (2026-02)."""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

ARG = "SUM(field('t_ds','plan'))"


async def _preview(client, headers, formula):
    r = await client.post("/metrics/preview", headers=headers, json={"formula": formula})
    assert r.status_code == 200, f"{formula}: {r.status_code} {r.text}"
    return r.json()["value"]


async def test_running_total(client, admin_headers, seed_dataset):
    v = await _preview(client, admin_headers, f"RUNNING_TOTAL({ARG}, grain='month')")
    assert v == 345  # 165 + 180


async def test_period_compare_delta(client, admin_headers, seed_dataset):
    v = await _preview(client, admin_headers, f"PERIOD_COMPARE({ARG}, 'month', mode='delta')")
    assert v == 15  # 180 - 165


async def test_period_compare_pct(client, admin_headers, seed_dataset):
    v = await _preview(client, admin_headers, f"PERIOD_COMPARE({ARG}, 'month', mode='pct')")
    assert abs(v - 180 / 165 * 100) < 0.01


async def test_share_of_total(client, admin_headers, seed_dataset):
    v = await _preview(client, admin_headers, f"SHARE_OF_TOTAL({ARG}, over='total')")
    assert abs(v - 180 / 345 * 100) < 0.01


async def test_running_total_in_expression(client, admin_headers, seed_dataset):
    # оконная функция как часть большего выражения
    v = await _preview(client, admin_headers, f"RUNNING_TOTAL({ARG}, grain='month') / 2")
    assert v == 172.5
