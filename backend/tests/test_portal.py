"""Раздел пользователя: инструкции, объявления, его главная.

Обычному сотруднику раньше были доступны список отчётов и кабинет. Здесь
проверяется то, ради чего раздел появился: он может прочитать инструкцию,
увидеть объявление администратора и понять, какие отчёты ему открыты и от
какого объекта.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db


async def test_instructions_visible_to_user_and_read_marks(client, admin_headers, viewer):
    """Пользователь видит опубликованные, черновики — нет; открытие гасит «новое»."""
    pub = await client.post("/instructions", headers=admin_headers, json={
        "title": "ztest_как_начать", "section": "ztest_раздел",
        "body": "Откройте раздел «Дашборды».", "position": 1})
    assert pub.status_code == 201, pub.text
    draft = await client.post("/instructions", headers=admin_headers, json={
        "title": "ztest_черновик", "is_published": False})
    assert draft.status_code == 201

    got = await client.get("/instructions", headers=viewer['headers'])
    titles = [i["title"] for i in got.json()["items"]]
    assert "ztest_как_начать" in titles
    assert "ztest_черновик" not in titles, "черновик пользователю показывать нельзя"

    mine = next(i for i in got.json()["items"] if i["title"] == "ztest_как_начать")
    assert mine["is_read"] is False and got.json()["unread"] >= 1

    # Открытие — отмечает прочитанным. Иначе «новое» висело бы вечно.
    one = await client.get(f"/instructions/{mine['id']}", headers=viewer['headers'])
    assert one.status_code == 200
    again = await client.get("/instructions", headers=viewer['headers'])
    assert next(i for i in again.json()["items"] if i["id"] == mine["id"])["is_read"] is True

    # Поиск идёт и по тексту: формулировку из середины помнят чаще названия.
    found = await client.get("/instructions?q=Дашборды", headers=viewer['headers'])
    assert any(i["id"] == mine["id"] for i in found.json()["items"])

    for r in (pub, draft):
        d = await client.delete(f"/instructions/{r.json()['id']}", headers=admin_headers)
        assert d.status_code == 204


async def test_user_cannot_write_instructions(client, viewer):
    """Инструкцию видит вся организация — писать её может только управляющий."""
    r = await client.post("/instructions", headers=viewer["headers"], json={"title": "ztest_нельзя"})
    assert r.status_code == 403


async def test_announcement_shows_until_it_expires(client, admin_headers, viewer):
    """Объявление видно пользователю, истёкшее — нет."""
    live = await client.post("/announcements", headers=admin_headers, json={
        "title": "ztest_работы", "body": "Суббота, 9:00–12:00", "important": True})
    assert live.status_code == 201, live.text
    old = await client.post("/announcements", headers=admin_headers, json={
        "title": "ztest_старое", "body": "прошлогоднее", "ends_at": "2020-01-01T00:00:00Z"})
    assert old.status_code == 201

    seen = await client.get("/announcements", headers=viewer['headers'])
    titles = [a["title"] for a in seen.json()]
    assert "ztest_работы" in titles
    assert "ztest_старое" not in titles, "срок вышел — объявление показывать нельзя"

    # Управляющий видит и истёкшие: ему нужно понимать, что было.
    all_ann = await client.get("/announcements?all=true", headers=admin_headers)
    assert "ztest_старое" in [a["title"] for a in all_ann.json()]

    async with db.acquire() as conn:
        # Создание объявления пишется в журнал: его видит вся организация.
        n = await conn.fetchval(
            "select count(*) from audit_log where entity_type='announcement' and action='create'")
        assert n >= 2

    for r in (live, old):
        d = await client.delete(f"/announcements/{r.json()['id']}", headers=admin_headers)
        assert d.status_code == 204
    async with db.acquire() as conn:
        await conn.execute("delete from audit_log where entity_type='announcement'")


async def test_portal_home_groups_dashboards_by_object(client, admin_headers, viewer, ids):
    """Главная пользователя: его отчёты сгруппированы по объекту, чужих нет."""
    r = await client.get("/home/portal", headers=viewer['headers'])
    assert r.status_code == 200, r.text
    data = r.json()
    assert set(data) >= {"announcements", "objects", "dashboards_total", "fresh_data",
                         "instructions", "show_featured", "stale_password"}
    # Отчёты сгруппированы: у каждой группы есть имя объекта и свой список.
    for g in data["objects"]:
        assert g["object_name"] and isinstance(g["dashboards"], list)
    assert data["dashboards_total"] == sum(len(g["dashboards"]) for g in data["objects"])
    # Раздел «Руководителю» по умолчанию выключен — он нужен единицам.
    assert data["show_featured"] is False
