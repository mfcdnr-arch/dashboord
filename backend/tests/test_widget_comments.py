"""Комментарий к КОНКРЕТНОЙ ЦИФРЕ (п. 8).

Обсуждение привязывалось только к дашборду: замечание «здесь занижено,
отделение переезжало» приходилось начинать с объяснения, о какой из тридцати
цифр речь.

Главная тонкость — не привязка к виджету, а **дата**. Виджет показывает
последний выпуск, поэтому замечание об августовском числе через неделю висело
бы рядом с сентябрьским и вводило бы в заблуждение молча. Поэтому вместе с
текстом сохраняется отчётная дата, которую человек ВИДЕЛ, и строка, если он
провалился в район.

Второй ленты не заводим: замечания к цифрам лежат в том же обсуждении отчёта —
иначе часть разговора была бы видна только тому, кто открыл нужный виджет.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import purge_dashboard


async def _dash(client, headers, name="ztest_wc"):
    did = (await client.post("/dashboards", headers=headers, json={"name": name})).json()["id"]
    pid = (await client.post(f"/dashboards/{did}/pages", headers=headers,
                             json={"name": "Обзор"})).json()["id"]
    wid = (await client.post(f"/dashboard-pages/{pid}/widgets", headers=headers,
           json={"name": "Обращения", "widget_type": "kpi",
                 "config": {"dataset_code": "t_ds", "value_field": "plan"}})).json()["id"]
    return did, pid, wid


async def test_comment_remembers_which_number_it_was_about(client, admin_headers, seed_dataset):
    """Замечание сохраняет отчётную дату и строку — иначе через неделю оно
    относилось бы к другому числу."""
    did, _, wid = await _dash(client, admin_headers)
    try:
        r = await client.post(f"/dashboards/{did}/comments", headers=admin_headers, json={
            "body": "Здесь занижено — отделение переезжало",
            "widget_id": wid, "period": "2026-02-01", "row_label": "Паспорт"})
        assert r.status_code == 201, r.text

        items = (await client.get(f"/dashboards/{did}/comments", headers=admin_headers)).json()["items"]
        c = items[0]
        assert c["widget_id"] == wid
        assert c["period"] == "2026-02-01", "дата цифры сохранена"
        assert c["row_label"] == "Паспорт"
        assert c["widget_name"] == "Обращения", "виджет назван по-человечески"
    finally:
        await purge_dashboard(did)


async def test_widget_thread_and_whole_discussion(client, admin_headers, seed_dataset):
    """Лента одной цифры отдаётся отдельно, но из общего обсуждения замечания
    к цифрам НЕ пропадают: иначе часть разговора видел бы только тот, кто
    открыл нужный виджет."""
    did, _, wid = await _dash(client, admin_headers)
    try:
        await client.post(f"/dashboards/{did}/comments", headers=admin_headers,
                          json={"body": "про отчёт целиком"})
        await client.post(f"/dashboards/{did}/comments", headers=admin_headers,
                          json={"body": "про эту цифру", "widget_id": wid, "period": "2026-02-01"})

        whole = (await client.get(f"/dashboards/{did}/comments", headers=admin_headers)).json()
        assert whole["total"] == 2, "общее обсуждение показывает и то, и другое"

        one = (await client.get(f"/dashboards/{did}/comments?widget_id={wid}",
                                headers=admin_headers)).json()
        assert one["total"] == 1
        assert one["items"][0]["body"] == "про эту цифру"

        general = next(c for c in whole["items"] if c["body"] == "про отчёт целиком")
        assert general["widget_id"] is None and general["period"] is None
    finally:
        await purge_dashboard(did)


async def test_counts_come_with_the_page(client, admin_headers, seed_dataset):
    """Счётчик 💬 приходит вместе со списком виджетов страницы — значок должен
    быть виден сразу, а не догружаться по одному."""
    did, pid, wid = await _dash(client, admin_headers)
    try:
        widgets = (await client.get(f"/dashboard-pages/{pid}/widgets",
                                    headers=admin_headers)).json()["widgets"]
        assert widgets[0]["comments_count"] == 0

        for i in range(2):
            await client.post(f"/dashboards/{did}/comments", headers=admin_headers,
                              json={"body": f"замечание {i}", "widget_id": wid,
                                    "period": "2026-02-01"})
        widgets = (await client.get(f"/dashboard-pages/{pid}/widgets",
                                    headers=admin_headers)).json()["widgets"]
        assert widgets[0]["comments_count"] == 2
    finally:
        await purge_dashboard(did)


async def test_foreign_widget_is_rejected(client, admin_headers, seed_dataset):
    """Замечание к чужой цифре не попадёт в чужое обсуждение.

    Видимость проверяется по ДАШБОРДУ, поэтому виджет обязан принадлежать
    именно ему — иначе через свой дашборд можно было бы писать в чужой.
    """
    did, _, _ = await _dash(client, admin_headers)
    other_did, _, other_wid = await _dash(client, admin_headers, name="ztest_wc2")
    try:
        r = await client.post(f"/dashboards/{did}/comments", headers=admin_headers,
                              json={"body": "чужая цифра", "widget_id": other_wid})
        # 404, а не 400: «не найден» — и это правильнее, чем 400, потому что
        # не раскрывает, что такой виджет существует на другом дашборде.
        assert r.status_code == 404
        assert "не найден" in r.json()["detail"]
    finally:
        await purge_dashboard(did)
        await purge_dashboard(other_did)


async def test_comment_dies_with_its_widget(client, admin_headers, seed_dataset):
    """Виджет удалили — замечание про «эту цифру» уходит с ним.

    Оно указывало бы в никуда: в отличие от слепка архива, комментарий не
    содержит самих данных и без своего виджета смысла не имеет.
    """
    did, _, wid = await _dash(client, admin_headers)
    try:
        await client.post(f"/dashboards/{did}/comments", headers=admin_headers,
                          json={"body": "про цифру", "widget_id": wid, "period": "2026-02-01"})
        await client.post(f"/dashboards/{did}/comments", headers=admin_headers,
                          json={"body": "про отчёт"})

        await client.delete(f"/widgets/{wid}", headers=admin_headers)
        left = (await client.get(f"/dashboards/{did}/comments", headers=admin_headers)).json()
        assert left["total"] == 1, "ушло только замечание к цифре"
        assert left["items"][0]["body"] == "про отчёт"
    finally:
        await purge_dashboard(did)


async def test_viewer_without_access_cannot_read_or_write(client, admin_headers, viewer, seed_dataset):
    """Обсуждение наследует видимость дашборда — и для чтения, и для записи."""
    did, _, wid = await _dash(client, admin_headers)
    try:
        r = await client.get(f"/dashboards/{did}/comments", headers=viewer["headers"])
        assert r.status_code == 404
        r = await client.post(f"/dashboards/{did}/comments", headers=viewer["headers"],
                              json={"body": "нельзя", "widget_id": wid})
        assert r.status_code == 404
    finally:
        await purge_dashboard(did)
