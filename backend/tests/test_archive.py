"""Архив дашбордов: слепок, месячные папки, доступ, unarchive, автоархивация."""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import purge_dashboard  # noqa: E402
from app import db  # noqa: E402
from app.modules.dashboards import _archive  # noqa: E402


async def _make_dashboard(client, headers, seed_dataset, name="t_arc_dash"):
    d = (await client.post("/dashboards", headers=headers, json={"name": name})).json()
    p = (await client.post(f"/dashboards/{d['id']}/pages", headers=headers, json={"name": "Обзор"})).json()
    r = await client.post(f"/dashboard-pages/{p['id']}/widgets", headers=headers,
                          json={"name": "KPI", "widget_type": "kpi",
                                "config": {"dataset_code": "t_ds", "value_field": "plan"}})
    assert r.status_code == 201
    return d["id"]


async def test_archive_snapshot_flow(client, admin_headers, seed_dataset):
    """Полный цикл: архивация → слепок с данными → скрытие из списка →
    поиск/месяцы → unarchive → удаление слепка."""
    did = await _make_dashboard(client, admin_headers, seed_dataset)
    try:
        r = await client.post(f"/dashboards/{did}/archive", headers=admin_headers,
                              json={"topic": "t_Тема", "note": "тест"})
        assert r.status_code == 201, r.text
        aid, month = r.json()["id"], r.json()["archive_month"]

        # повторная архивация — 400 «уже в архиве»
        r2 = await client.post(f"/dashboards/{did}/archive", headers=admin_headers, json={})
        assert r2.status_code == 400

        # скрыт из основного списка
        lst = (await client.get("/dashboards?q=t_arc_dash", headers=admin_headers)).json()
        assert lst["total"] == 0

        # месяцы и поиск по теме
        months = (await client.get("/archive/months", headers=admin_headers)).json()
        assert any(m["month"] == month for m in months)
        found = (await client.get("/archive", headers=admin_headers,
                                  params={"q": "t_тема"})).json()
        assert len(found) == 1 and found[0]["topic"] == "t_Тема"

        # слепок: данные заморожены (KPI = сумма plan активного выпуска = 180)
        full = (await client.get(f"/archive/{aid}", headers=admin_headers)).json()
        w = full["snapshot"]["pages"][0]["widgets"][0]
        assert w["widget_type"] == "kpi" and w["data"]["value"] == seed_dataset["plan_sum"]

        # экспорт слепка
        x = await client.get(f"/archive/{aid}/export.xlsx", headers=admin_headers)
        assert x.status_code == 200 and x.content[:2] == b"PK"

        # возврат из архива → прежний статус (draft), снова в списке
        u = await client.post(f"/archive/{aid}/unarchive", headers=admin_headers)
        assert u.status_code == 200 and u.json()["publication_status"] == "draft"
        lst2 = (await client.get("/dashboards?q=t_arc_dash", headers=admin_headers)).json()
        assert lst2["total"] == 1

        # удаление слепка (админ)
        assert (await client.delete(f"/archive/{aid}", headers=admin_headers)).status_code == 204
        assert (await client.get(f"/archive/{aid}", headers=admin_headers)).status_code == 404
    finally:
        await purge_dashboard(did)
        async with db.acquire() as conn:
            await conn.execute("delete from dashboard_archive where dashboard_name='t_arc_dash'")


async def test_archive_access_gating(client, admin_headers, seed_dataset, viewer):
    """Обычный пользователь: без допуска 403, с допуском видит; отзыв возвращает 403.
    Удаление слепка зрителю запрещено (403)."""
    did = await _make_dashboard(client, admin_headers, seed_dataset, name="t_arc_dash2")
    aid = None
    try:
        aid = (await client.post(f"/dashboards/{did}/archive", headers=admin_headers, json={})).json()["id"]

        assert (await client.get("/archive/me", headers=viewer["headers"])).json()["allowed"] is False
        assert (await client.get("/archive", headers=viewer["headers"])).status_code == 403
        assert (await client.get(f"/archive/{aid}", headers=viewer["headers"])).status_code == 403

        # допуск
        r = await client.post("/archive-access", headers=admin_headers, json={"user_id": viewer["id"]})
        assert r.status_code == 201
        assert (await client.get("/archive/me", headers=viewer["headers"])).json()["allowed"] is True
        got = await client.get(f"/archive/{aid}", headers=viewer["headers"])
        assert got.status_code == 200

        # зритель НЕ может удалять/возвращать/архивировать
        assert (await client.delete(f"/archive/{aid}", headers=viewer["headers"])).status_code == 403
        assert (await client.post(f"/archive/{aid}/unarchive", headers=viewer["headers"])).status_code == 403

        # отзыв допуска
        assert (await client.delete(f"/archive-access/{viewer['id']}", headers=admin_headers)).status_code == 204
        assert (await client.get("/archive", headers=viewer["headers"])).status_code == 403
    finally:
        await purge_dashboard(did)
        async with db.acquire() as conn:
            await conn.execute("delete from dashboard_archive where dashboard_name='t_arc_dash2'")
            await conn.execute("delete from archive_access where user_id=$1::uuid", viewer["id"])


async def test_monthly_auto_archive(client, admin_headers, seed_dataset, ids):
    """Автоархивация: флажок auto_archive → run_monthly_auto_archive создаёт слепок
    за прошлый месяц; повторный запуск идемпотентен."""
    did = await _make_dashboard(client, admin_headers, seed_dataset, name="t_arc_dash3")
    try:
        r = await client.post(f"/dashboards/{did}/auto-archive", headers=admin_headers,
                              json={"enabled": True})
        assert r.status_code == 200 and r.json()["auto_archive"] is True

        async with db.acquire() as conn:
            n1 = await _archive.run_monthly_auto_archive(conn, ids["org"])
            n2 = await _archive.run_monthly_auto_archive(conn, ids["org"])
        assert n1 >= 1 and n2 == 0  # второй прогон ничего не дублирует

        items = (await client.get("/archive", headers=admin_headers, params={"q": "t_arc_dash3"})).json()
        assert len(items) == 1 and items[0]["auto"] is True and items[0]["topic"] == "Автоархив"
        # дашборд при автоархивации ОСТАЁТСЯ в основном списке
        lst = (await client.get("/dashboards?q=t_arc_dash3", headers=admin_headers)).json()
        assert lst["total"] == 1
    finally:
        await purge_dashboard(did)
        async with db.acquire() as conn:
            await conn.execute("delete from dashboard_archive where dashboard_name='t_arc_dash3'")
