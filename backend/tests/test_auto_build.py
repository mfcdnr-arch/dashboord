"""Авто-сборка дашборда по объекту.

Главное правило: сколько числовых показателей человек увидел в предпросмотре
разметки, столько карточек он должен получить и на собранном дашборде. Раньше
брались только первые ДВА поля — на госформе из 14 граф это выглядело как
потеря данных (замечание заказчика 11.08.2026).
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db  # noqa: E402
from conftest import purge_dashboard  # noqa: E402

FIELDS = [("f1", "Обращения"), ("f2", "Отправлено"), ("f3", "Доставлено"),
          ("f4", "Записались"), ("f5", "Отказы"), ("f6", "Повторные")]


async def _seed_fields(org_id):
    """seed_dataset вставляет значения в обход конвейера распознавания и НЕ
    заводит метаданные полей — а авто-сборка берёт показатели именно из них."""
    async with db.acquire() as conn:
        rel = await conn.fetchrow(
            "select id, object_id from dataset_releases where organization_id=$1 and code='t_ds' "
            "and status<>'superseded' order by reporting_period_start desc limit 1", org_id)
        for code, name in FIELDS:
            await conn.execute(
                "insert into canonical_fields(object_id,code,name,data_type) values($1,$2,$3,'number') "
                "on conflict (object_id,code) do nothing", rel["object_id"], code, name)
            await conn.execute(
                "insert into dataset_release_fields(dataset_release_id,canonical_field_code) values($1,$2) "
                "on conflict do nothing", rel["id"], code)
    return rel


async def _cleanup_fields(rel):
    async with db.acquire() as conn:
        codes = [c for c, _ in FIELDS]
        await conn.execute(
            "delete from dataset_release_fields where dataset_release_id=$1 and canonical_field_code=any($2::text[])",
            rel["id"], codes)
        await conn.execute(
            "delete from canonical_fields where object_id=$1 and code=any($2::text[])", rel["object_id"], codes)


async def test_auto_build_makes_kpi_for_every_numeric_field(client, admin_headers, seed_dataset, ids):
    rel = await _seed_fields(ids["org"])
    did = None
    try:
        r = await client.post("/dashboards/auto", headers=admin_headers,
                              json={"object_id": str(rel["object_id"]), "name": "ztest_auto"})
        assert r.status_code in (200, 201), r.text
        did = r.json()["dashboard_id"]

        async with db.acquire() as conn:
            rows = await conn.fetch(
                "select widget_type, name, config, position_x, position_y, width "
                "from widgets where dashboard_id=$1::uuid order by position_y, position_x", did)

        kpis = [w for w in rows if w["widget_type"] == "kpi"]
        assert len(kpis) == len(FIELDS), \
            f"карточек должно быть столько же, сколько показателей: ожидали {len(FIELDS)}, получили {len(kpis)}"

        # каждый показатель представлен ровно один раз
        import json
        used = sorted(json.loads(w["config"])["value_field"] if isinstance(w["config"], str)
                      else w["config"]["value_field"] for w in kpis)
        assert used == sorted(c for c, _ in FIELDS)

        # по 4 карточки в ряд, сетка 12 колонок заполняется без дыр
        assert {w["position_x"] for w in kpis} == {0, 3, 6, 9}
        assert all(w["width"] == 3 for w in kpis)

        types = [w["widget_type"] for w in rows]
        assert "table" in types, "таблица-первичка обязательна"
        assert "bar" in types, "график по строкам обязателен"
        assert "compare" in types, "нужен общий график: 6 карточек не показывают соотношение"
    finally:
        if did:
            await purge_dashboard(did)
        await _cleanup_fields(rel)


async def test_auto_build_makes_one_dynamics_per_field_without_duplicates(
        client, admin_headers, seed_dataset, ids):
    """Когда периодов несколько, тренд строится по КАЖДОМУ показателю — иначе
    дашборд по полутора десяткам форм выглядит так, будто взята одна дата.
    И ровно ОДИН на показатель: первый показатель однажды получил два
    одинаковых графика подряд (ряд графиков + сетка трендов)."""
    rel = await _seed_fields(ids["org"])
    did = None
    try:
        r = await client.post("/dashboards/auto", headers=admin_headers,
                              json={"object_id": str(rel["object_id"]), "name": "ztest_auto_dyn"})
        did = r.json()["dashboard_id"]
        async with db.acquire() as conn:
            rows = await conn.fetch(
                "select config from widgets where dashboard_id=$1::uuid and widget_type='dynamics'", did)
        import json
        fields = [json.loads(w["config"])["value_field"] if isinstance(w["config"], str)
                  else w["config"]["value_field"] for w in rows]
        assert sorted(fields) == sorted(c for c, _ in FIELDS), \
            f"тренд нужен по каждому показателю ровно один раз, получили: {sorted(fields)}"
    finally:
        if did:
            await purge_dashboard(did)
        await _cleanup_fields(rel)


async def test_auto_build_widgets_do_not_overlap(client, admin_headers, seed_dataset, ids):
    """Виджеты не должны накладываться друг на друга: раскладка считается
    вручную, и смещение рядов легко сломать при правке."""
    rel = await _seed_fields(ids["org"])
    did = None
    try:
        r = await client.post("/dashboards/auto", headers=admin_headers,
                              json={"object_id": str(rel["object_id"]), "name": "ztest_auto_grid"})
        did = r.json()["dashboard_id"]
        async with db.acquire() as conn:
            rows = await conn.fetch(
                "select name, position_x x, position_y y, width w, height h "
                "from widgets where dashboard_id=$1::uuid", did)
        boxes = [(w["x"], w["y"], w["x"] + w["w"], w["y"] + w["h"], w["name"]) for w in rows]
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                overlap = not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])
                assert not overlap, f"пересекаются «{a[4]}» и «{b[4]}»"
            assert a[2] <= 12, f"«{a[4]}» выходит за 12 колонок"
    finally:
        if did:
            await purge_dashboard(did)
        await _cleanup_fields(rel)
