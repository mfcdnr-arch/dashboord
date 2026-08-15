"""Значения показателей в списке: что метрика считает прямо сейчас.

Раньше это можно было узнать, только открыв показатель и нажав предпросмотр:
при полутора десятках показателей — полтора десятка заходов. Хуже другое:
сломанная формула ничем себя не выдавала, она выглядела обычной строкой
списка и обнаруживалась уже на дашборде.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db


async def test_values_show_result_and_name_broken_ones(client, admin_headers, seed_dataset, ids):
    """Считающийся показатель отдаёт число, сломанный — объяснение, а не тишину."""
    ok = await client.post("/metrics", headers=admin_headers,
                           json={"code": "ztest_val_ok", "name": "ztest считается"})
    bad = await client.post("/metrics", headers=admin_headers,
                            json={"code": "ztest_val_bad", "name": "ztest не считается"})
    empty = await client.post("/metrics", headers=admin_headers,
                              json={"code": "ztest_val_empty", "name": "ztest без формулы"})
    try:
        await client.post(f"/metrics/{ok.json()['id']}/versions", headers=admin_headers,
                          json={"formula": f"SUM(field('{seed_dataset['code']}','plan'))", "unit": "шт"})
        # Формула ссылается на несуществующий датасет — версия создаётся, но не считается.
        await client.post(f"/metrics/{bad.json()['id']}/versions", headers=admin_headers,
                          json={"formula": "SUM(field('ztest_no_such_ds','plan'))"})

        r = await client.get("/metrics/values", headers=admin_headers)
        assert r.status_code == 200, r.text
        by_code = {i["code"]: i for i in r.json()["items"]}

        assert by_code["ztest_val_ok"]["value"] == seed_dataset["plan_sum"]
        assert by_code["ztest_val_ok"]["unit"] == "шт"
        assert by_code["ztest_val_ok"]["error"] is None

        assert by_code["ztest_val_bad"]["value"] is None
        assert by_code["ztest_val_bad"]["error"], "сломанная формула обязана объясниться"

        assert by_code["ztest_val_empty"]["value"] is None
        assert "версии формулы" in by_code["ztest_val_empty"]["error"]
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from metric_versions where metric_id in "
                               "(select id from metrics where code like 'ztest_val_%')")
            await conn.execute("delete from metrics where code like 'ztest_val_%'")


async def test_values_use_best_version_like_widgets(client, admin_headers, seed_dataset):
    """Берётся та же версия, что и у виджета: одобренная важнее черновика.

    Иначе список показывал бы одно, а дашборд считал другое — расхождение,
    которое человек заметит в последнюю очередь.
    """
    m = await client.post("/metrics", headers=admin_headers,
                          json={"code": "ztest_val_best", "name": "ztest лучшая версия"})
    mid = m.json()["id"]
    try:
        v1 = await client.post(f"/metrics/{mid}/versions", headers=admin_headers,
                               json={"formula": f"SUM(field('{seed_dataset['code']}','plan'))"})
        await client.post(f"/metrics/versions/{v1.json()['version_id']}/validate", headers=admin_headers)
        # Более новая версия остаётся черновиком — приоритет у проверенной.
        await client.post(f"/metrics/{mid}/versions", headers=admin_headers,
                          json={"formula": f"SUM(field('{seed_dataset['code']}','fact'))"})

        r = await client.get("/metrics/values", headers=admin_headers)
        item = next(i for i in r.json()["items"] if i["code"] == "ztest_val_best")
        assert item["value"] == seed_dataset["plan_sum"], item
        assert item["status"] == "validated"
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from metric_versions where metric_id=$1::uuid", mid)
            await conn.execute("delete from metrics where id=$1::uuid", mid)
