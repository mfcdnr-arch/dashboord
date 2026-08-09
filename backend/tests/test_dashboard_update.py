"""Правка дашборда: название и описание.

Эндпоинта на изменение дашборда не существовало вовсе — имя задавалось при
создании и оставалось навсегда, опечатку исправить было нечем. Здесь
фиксируем контракт: частичность (описание меняется, не трогая имя), запрет
пустого имени и права как у удаления (чужой дашборд правит только админ).
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _mk(client, headers, name):
    return (await client.post("/dashboards", headers=headers, json={"name": name})).json()["id"]


async def test_rename_and_describe(client, admin_headers):
    did = await _mk(client, admin_headers, "ztest_upd_old")

    r = await client.patch(f"/dashboards/{did}", headers=admin_headers,
                           json={"name": "ztest_upd_new", "description": "  что показывает  "})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "ztest_upd_new"
    assert r.json()["description"] == "что показывает"  # пробелы по краям срезаны

    # частичность: меняем только описание — имя остаётся
    r = await client.patch(f"/dashboards/{did}", headers=admin_headers,
                           json={"description": "другое"})
    assert r.status_code == 200
    assert r.json()["name"] == "ztest_upd_new"
    assert r.json()["description"] == "другое"

    # описание можно стереть
    r = await client.patch(f"/dashboards/{did}", headers=admin_headers, json={"description": None})
    assert r.status_code == 200
    assert r.json()["description"] is None

    # изменения видны при чтении
    got = (await client.get(f"/dashboards/{did}", headers=admin_headers)).json()
    assert got["dashboard"]["name"] == "ztest_upd_new"

    await client.delete(f"/dashboards/{did}", headers=admin_headers)


async def test_empty_name_and_empty_patch_rejected(client, admin_headers):
    did = await _mk(client, admin_headers, "ztest_upd_guard")

    r = await client.patch(f"/dashboards/{did}", headers=admin_headers, json={"name": "   "})
    assert r.status_code == 400, r.text

    # пустое тело менять нечего — 400, а не молчаливый успех
    assert (await client.patch(f"/dashboards/{did}", headers=admin_headers, json={})).status_code == 400

    # имя не пострадало
    got = (await client.get(f"/dashboards/{did}", headers=admin_headers)).json()
    assert got["dashboard"]["name"] == "ztest_upd_guard"

    await client.delete(f"/dashboards/{did}", headers=admin_headers)


async def test_unknown_dashboard_is_404(client, admin_headers):
    r = await client.patch("/dashboards/00000000-0000-0000-0000-000000000000",
                           headers=admin_headers, json={"name": "ztest_nope"})
    assert r.status_code == 404, r.text
