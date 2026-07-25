"""Комментарии / обсуждение к дашбордам: доступ по RLS (кто видит дашборд — тот
пишет), удаление автором/привилегированным, уведомление автору дашборда."""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import purge_dashboard


async def test_comment_flow_rls_and_notify(client, admin_headers, viewer):
    # admin — автор дашборда; выдаём грант viewer + публикуем, чтобы он видел
    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_cmt"})).json()["id"]
    try:
        await client.post(f"/dashboards/{did}/grants", headers=admin_headers,
                          json={"grantee_type": "user", "user_id": viewer["id"]})
        await client.post(f"/dashboards/{did}/publish", headers=admin_headers)

        # viewer оставляет комментарий → 201
        r = await client.post(f"/dashboards/{did}/comments", headers=viewer["headers"], json={"body": "Вопрос по KPI"})
        assert r.status_code == 201, r.text
        cid = r.json()["id"]

        # список видят и viewer, и admin; can_delete: свой=да
        r = await client.get(f"/dashboards/{did}/comments", headers=viewer["headers"])
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["body"] == "Вопрос по KPI"
        assert body["items"][0]["can_delete"] is True  # автор

        # автор дашборда (admin) получил уведомление о комментарии
        r = await client.get("/notifications", headers=admin_headers)
        assert any(n["event_type"] == "dashboard.comment" and n["entity_id"] == did for n in r.json()["items"])

        # admin (привилегированный) тоже может удалять чужой комментарий → can_delete=true
        r = await client.get(f"/dashboards/{did}/comments", headers=admin_headers)
        assert r.json()["items"][0]["can_delete"] is True

        # пустой комментарий → 422 (pydantic min_length)
        r = await client.post(f"/dashboards/{did}/comments", headers=viewer["headers"], json={"body": "  "})
        assert r.status_code in (400, 422)

        # viewer удаляет свой → 204, список пуст
        assert (await client.delete(f"/dashboards/{did}/comments/{cid}", headers=viewer["headers"])).status_code == 204
        assert (await client.get(f"/dashboards/{did}/comments", headers=viewer["headers"])).json()["total"] == 0
    finally:
        await purge_dashboard(did)


async def test_comment_denied_without_view(client, admin_headers, viewer):
    """Непривилегированный без гранта не видит дашборд → и обсуждение недоступно (404)."""
    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_cmt2"})).json()["id"]
    try:
        assert (await client.get(f"/dashboards/{did}/comments", headers=viewer["headers"])).status_code == 404
        r = await client.post(f"/dashboards/{did}/comments", headers=viewer["headers"], json={"body": "нельзя"})
        assert r.status_code == 404
    finally:
        await purge_dashboard(did)


async def test_comment_delete_foreign_forbidden(client, admin_headers, viewer):
    """viewer не может удалить чужой (admin) комментарий."""
    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_cmt3"})).json()["id"]
    try:
        await client.post(f"/dashboards/{did}/grants", headers=admin_headers,
                          json={"grantee_type": "user", "user_id": viewer["id"]})
        await client.post(f"/dashboards/{did}/publish", headers=admin_headers)
        cid = (await client.post(f"/dashboards/{did}/comments", headers=admin_headers, json={"body": "от админа"})).json()["id"]
        r = await client.delete(f"/dashboards/{did}/comments/{cid}", headers=viewer["headers"])
        assert r.status_code in (400, 403)
    finally:
        await purge_dashboard(did)
