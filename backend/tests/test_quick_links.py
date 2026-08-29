"""Быстрый доступ (квик-меню): куратор-меню коротких названий отчётов.

Проверяем: CRUD только staff; список фильтруется по видимости КАЖДОГО
пункта отдельно — дашборд по RLS (грант/публикация), раздел по гейту
(staff / show_featured); неизвестный раздел отклоняется при создании;
реордер полным списком, как у витрин.
"""
import pytest

from app import db

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import purge_dashboard


async def test_dashboard_link_hidden_without_access(client, admin_headers, viewer):
    """Пункт на дашборд виден только тому, кому дашборд реально открыт."""
    d = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_ql_dash"})).json()["id"]
    link_id = None
    try:
        r = await client.post("/quick-links", headers=admin_headers,
                              json={"label": "MAX", "kind": "dashboard", "dashboard_id": d})
        assert r.status_code == 201, r.text
        link_id = r.json()["id"]

        # admin (staff, видит все дашборды) — пункт в списке
        items = (await client.get("/quick-links", headers=admin_headers)).json()["items"]
        assert any(x["id"] == link_id for x in items)

        # viewer без гранта — пункта нет вовсе (не только скрыта ссылка, а
        # само существование пункта не палится)
        items = (await client.get("/quick-links", headers=viewer["headers"])).json()["items"]
        assert not any(x["id"] == link_id for x in items)

        # выдали грант и опубликовали — теперь виден
        await client.post(f"/dashboards/{d}/grants", headers=admin_headers,
                          json={"grantee_type": "user", "user_id": viewer["id"]})
        await client.post(f"/dashboards/{d}/publish", headers=admin_headers)
        items = (await client.get("/quick-links", headers=viewer["headers"])).json()["items"]
        found = next((x for x in items if x["id"] == link_id), None)
        assert found is not None and found["label"] == "MAX" and found["dashboard_id"] == d
    finally:
        if link_id:
            await client.delete(f"/quick-links/{link_id}", headers=admin_headers)
        await purge_dashboard(d)


async def test_section_link_gated_by_staff_or_featured(client, admin_headers, viewer):
    """Пункт на раздел («Статистика услуг») гейтится тем же правилом, что и
    пункт бокового меню — staff всегда, иначе по show_featured."""
    link_id = None
    try:
        r = await client.post("/quick-links", headers=admin_headers,
                              json={"label": "Статистика отделов", "kind": "section", "section": "dnrstats"})
        assert r.status_code == 201, r.text
        link_id = r.json()["id"]

        items = (await client.get("/quick-links", headers=admin_headers)).json()["items"]
        assert any(x["id"] == link_id and x["section"] == "dnrstats" for x in items)

        items = (await client.get("/quick-links", headers=viewer["headers"])).json()["items"]
        assert not any(x["id"] == link_id for x in items)

        async with db.acquire() as conn:
            await conn.execute("update users set show_featured=true where id=$1::uuid", viewer["id"])
        try:
            items = (await client.get("/quick-links", headers=viewer["headers"])).json()["items"]
            assert any(x["id"] == link_id for x in items)
        finally:
            async with db.acquire() as conn:
                await conn.execute("update users set show_featured=false where id=$1::uuid", viewer["id"])
    finally:
        if link_id:
            await client.delete(f"/quick-links/{link_id}", headers=admin_headers)


async def test_open_section_always_visible(client, admin_headers, viewer):
    """«Дашборды»/«Инструкции» без гейта — виден плоскому пользователю сразу."""
    link_id = None
    try:
        r = await client.post("/quick-links", headers=admin_headers,
                              json={"label": "Все отчёты", "kind": "section", "section": "dashboards"})
        link_id = r.json()["id"]
        items = (await client.get("/quick-links", headers=viewer["headers"])).json()["items"]
        assert any(x["id"] == link_id for x in items)
    finally:
        if link_id:
            await client.delete(f"/quick-links/{link_id}", headers=admin_headers)


async def test_unknown_section_rejected(client, admin_headers):
    r = await client.post("/quick-links", headers=admin_headers,
                          json={"label": "Пользователи", "kind": "section", "section": "users"})
    assert r.status_code == 400
    assert "users" in r.text


async def test_reorder_full_set_only(client, admin_headers):
    ids = []
    try:
        for label in ("A", "B", "C"):
            r = await client.post("/quick-links", headers=admin_headers,
                                  json={"label": label, "kind": "section", "section": "instructions"})
            ids.append(r.json()["id"])

        # Реордер — набор ВСЕГО меню организации, не только своих трёх пунктов
        # (в dev-БД могут жить и другие, настоящие пункты) — считаем набор явно,
        # а не предполагаем пустое меню.
        full = [x["id"] for x in (await client.get("/quick-links", headers=admin_headers)).json()["items"]]

        # неполный набор отклонён
        r = await client.post("/quick-links/reorder", headers=admin_headers, json={"ids": full[:-1]})
        assert r.status_code == 400

        # полный набор с нашей тройкой в обратном порядке — принимается
        others = [x for x in full if x not in ids]
        rev = list(reversed(ids))
        r = await client.post("/quick-links/reorder", headers=admin_headers, json={"ids": others + rev})
        assert r.status_code == 200
        items = (await client.get("/quick-links", headers=admin_headers)).json()["items"]
        got = [x["id"] for x in items if x["id"] in ids]
        assert got == rev
    finally:
        for lid in ids:
            await client.delete(f"/quick-links/{lid}", headers=admin_headers)


async def test_write_requires_staff(client, viewer):
    r = await client.post("/quick-links", headers=viewer["headers"],
                          json={"label": "X", "kind": "section", "section": "dashboards"})
    assert r.status_code == 403
