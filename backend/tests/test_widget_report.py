"""«Сообщить о проблеме» прямо с виджета (п. 15 — обратная связь).

Ценность кнопки не в том, что она заводит обращение (это умеет и «Кабинет»), а
в том, что человеку НЕ НУЖНО объяснять, где он это увидел: контекст —
дашборд, страница, показатель и число на экране — собирает сервер. Поэтому
проверяется прежде всего он:

  • в обращение попали название отчёта, страницы, виджета и ТО ЖЕ значение,
    которое считает сам виджет (иначе администратор разбирает не ту цифру);
  • жалоба на недоступный виджет невозможна — иначе кнопка стала бы способом
    узнать названия чужих отчётов и показателей;
  • повторное нажатие дописывает в открытое обращение, а не заводит второе;
  • сотрудник, пишущий в СВОЁМ обращении, не переводит его в «есть ответ» —
    он заявитель, а не администрация.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db


async def _dash(client, headers, name):
    r = await client.post("/dashboards", headers=headers, json={"name": name})
    did = r.json()["id"]
    r = await client.post(f"/dashboards/{did}/pages", headers=headers, json={"name": "Обзор"})
    return did, r.json()["id"]


async def _widget(client, headers, page_id, name, cfg, wtype="kpi"):
    r = await client.post(f"/dashboard-pages/{page_id}/widgets", headers=headers,
                          json={"name": name, "widget_type": wtype, "config": cfg})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def _drop(dids, appeal_ids=()):
    async with db.acquire() as conn:
        for aid in appeal_ids:
            await conn.execute("delete from appeal_messages where appeal_id=$1::uuid", aid)
            await conn.execute("delete from audit_log where entity_id=$1::uuid", aid)
            await conn.execute("delete from appeals where id=$1::uuid", aid)
        for did in dids:
            await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
            await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
            await conn.execute("delete from access_grants where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from audit_log where entity_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)


async def test_report_carries_context_and_value(client, admin_headers, seed_dataset):
    """Обращение приходит с ответом на вопрос «где», а не только «что»."""
    did, pid = await _dash(client, admin_headers, "ztest_rep_ctx")
    aid = None
    try:
        wid = await _widget(client, admin_headers, pid, "ztest Карточка плана",
                            {"dataset_code": seed_dataset["code"], "value_field": "plan"})
        r = await client.post(f"/widgets/{wid}/report-problem", headers=admin_headers,
                              json={"kind": "wrong_value", "comment": "Цифра не сходится"})
        assert r.status_code == 201, r.text
        out = r.json()
        aid = out["appeal_id"]
        assert out["appended"] is False
        # Тема сама называет отчёт и виджет: в очереди администратора видно, о
        # чём речь, без открывания переписки.
        assert "ztest Карточка плана" in out["subject"] and "ztest_rep_ctx" in out["subject"]

        r = await client.get(f"/appeals/{aid}", headers=admin_headers)
        assert r.status_code == 200, r.text
        detail = r.json()
        body = detail["messages"][0]["body"]
        assert "Цифра не сходится" in body
        assert "ztest_rep_ctx" in body and "Обзор" in body and "ztest Карточка плана" in body
        # Значение в обращении — ТО ЖЕ, что показывает виджет. Разойдись они,
        # администратор разбирал бы не ту цифру.
        rd = await client.get(f"/widgets/{wid}/data", headers=admin_headers)
        assert str(int(rd.json()["value"])) in body.replace(" ", " ").replace(" ", "")

        # Ссылки для перехода к отчёту — иначе разбор начинается с поиска
        # дашборда по названию среди десятков.
        ctx = detail["context"]
        assert ctx["dashboard_id"] == did and ctx["page_id"] == pid and ctx["widget_id"] == wid
        assert ctx["kind"] == "wrong_value"
    finally:
        await _drop([did], [aid] if aid else [])


async def test_repeat_appends_and_author_staff_does_not_answer_himself(client, admin_headers, seed_dataset):
    """Второе нажатие — в тот же тред; и оно НЕ помечает обращение отвеченным."""
    did, pid = await _dash(client, admin_headers, "ztest_rep_dup")
    aid = None
    try:
        wid = await _widget(client, admin_headers, pid, "ztest Карточка факта",
                            {"dataset_code": seed_dataset["code"], "value_field": "fact"})
        first = (await client.post(f"/widgets/{wid}/report-problem", headers=admin_headers,
                                   json={"kind": "no_data", "comment": "Пусто"})).json()
        aid = first["appeal_id"]
        second = (await client.post(f"/widgets/{wid}/report-problem", headers=admin_headers,
                                    json={"kind": "no_data", "comment": "И снова пусто"})).json()
        assert second["appended"] is True and second["appeal_id"] == aid

        r = await client.get(f"/appeals/{aid}", headers=admin_headers)
        detail = r.json()
        assert len(detail["messages"]) == 2
        # Автор пишет в своём обращении как ЗАЯВИТЕЛЬ, даже если он сотрудник:
        # иначе жалоба сама себя переводила бы в «есть ответ» и уходила из очереди.
        assert detail["status"] == "open"
        assert all(m["is_staff"] is False for m in detail["messages"])

        # Комментарий необязателен: вид проблемы + контекст уже отвечают на «что» и «где».
        r = await client.post(f"/widgets/{wid}/report-problem", headers=admin_headers,
                              json={"kind": "unclear"})
        assert r.status_code == 201
    finally:
        await _drop([did], [aid] if aid else [])


async def test_cannot_report_on_invisible_widget(client, admin_headers, viewer, seed_dataset):
    """Пожаловаться можно только на то, что тебе показывают: иначе кнопка стала
    бы способом узнать названия чужих отчётов и показателей."""
    did, pid = await _dash(client, admin_headers, "ztest_rep_secret")
    try:
        wid = await _widget(client, admin_headers, pid, "ЧУЖОЙ показатель",
                            {"dataset_code": seed_dataset["code"], "value_field": "plan"})
        r = await client.post(f"/widgets/{wid}/report-problem", headers=viewer["headers"],
                              json={"kind": "other", "comment": "x"})
        assert r.status_code == 404, r.text
        # Название чужого виджета не должно просочиться даже в текст отказа.
        assert "ЧУЖОЙ" not in r.text

        # Неизвестный вид проблемы — отказ, а не молчаливая подстановка «другое»:
        # подписи в интерфейсе и в тексте обращения задаёт сервер.
        r = await client.post(f"/widgets/{wid}/report-problem", headers=admin_headers,
                              json={"kind": "не-такой-вид", "comment": "x"})
        assert r.status_code == 400
    finally:
        await _drop([did])


async def test_broken_widget_can_still_be_reported(client, admin_headers):
    """Сбой расчёта не отменяет жалобу — наоборот, текст ошибки уезжает в
    обращение: часто это и есть ответ на вопрос «почему у меня пусто»."""
    did, pid = await _dash(client, admin_headers, "ztest_rep_broken")
    aid = None
    try:
        wid = await _widget(client, admin_headers, pid, "ztest Сломанный",
                            {"dataset_code": "нет-такого-датасета", "value_field": "plan"})
        r = await client.post(f"/widgets/{wid}/report-problem", headers=admin_headers,
                              json={"kind": "broken", "comment": "Ничего не видно"})
        assert r.status_code == 201, r.text
        aid = r.json()["appeal_id"]
        body = (await client.get(f"/appeals/{aid}", headers=admin_headers)).json()["messages"][0]["body"]
        assert "не считается" in body
    finally:
        await _drop([did], [aid] if aid else [])
