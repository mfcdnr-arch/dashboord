"""Одноимённые дашборды: система переспрашивает, а не создаёт молча.

Проверка жила только в ручном создании, поэтому мастер авто-сборки завёл
заказчику ТРИ «Дашборд «ИТ»» — в списке и в отчёте о популярности они
неразличимы, и руководитель может открыть заброшенную копию, считая её
актуальной. Теперь проверка стоит в `create_dashboard`, то есть общая для
всех путей: вручную, мастером, «План/факт», из шаблона, переносом.

Именно переспрос, а не запрет: копия «на следующий год» с тем же именем
законна — решает человек.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import purge_dashboard  # noqa: E402

from app import db
from app.modules.dashboards import service as svc


async def test_manual_create_asks_and_can_be_forced(client, admin_headers):
    name = "ztest_dup_name"
    a = await client.post("/dashboards", headers=admin_headers, json={"name": name})
    assert a.status_code == 201, a.text

    b = await client.post("/dashboards", headers=admin_headers, json={"name": name})
    assert b.status_code == 409, "второй дашборд с тем же именем обязан переспросить"
    detail = b.json()["detail"]
    assert "уже есть" in detail["message"], detail
    assert detail["duplicate"]["dashboard_id"] == a.json()["id"], "нужно назвать, с чем совпало"

    # Осознанное согласие — создаём.
    c = await client.post("/dashboards", headers=admin_headers, json={"name": name, "force": True})
    assert c.status_code == 201

    # Регистр и лишние пробелы совпадением считаются: «ИТ» и «ит » — одно имя.
    d = await client.post("/dashboards", headers=admin_headers, json={"name": "  ZTEST_DUP_NAME "})
    assert d.status_code == 409

    for r in (a, c):
        await purge_dashboard(r.json()["id"])


async def test_check_is_shared_by_every_creation_path(client, admin_headers, ids):
    """Проверка стоит в сервисе, а не в обработчике: её видят все пути.

    Проверяем это на самом сервисе — так тест не зависит от того, какой
    эндпоинт добавят следующим.
    """
    async with db.acquire() as conn:
        org, user = ids["org"], ids["admin"]
        first = await svc.create_dashboard(conn, org, user, "ztest_dup_svc", None, None)
        try:
            with pytest.raises(svc.DuplicateDashboardName) as err:
                await svc.create_dashboard(conn, org, user, "ztest_dup_svc", None, None)
            assert err.value.duplicate["dashboard_id"] == str(first["id"])
            # С явным согласием — создаётся.
            second = await svc.create_dashboard(conn, org, user, "ztest_dup_svc", None, None, force=True)
            second_id = str(second["id"])
        finally:
            first_id = str(first["id"])
    await purge_dashboard(second_id)
    await purge_dashboard(first_id)
