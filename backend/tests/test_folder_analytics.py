"""Аналитика по папке объекта (п. 8 списка заказчика).

Заказчик назвал четыре вопроса, на которые экран обязан отвечать: что в
цифрах, можно ли им верить, что уже построено и как объект выглядит на фоне
остальных. Тесты проверяют не наличие блоков, а правильность ответов:

1. **Свод не расходится с дашбордом** — значения берутся из активного выпуска,
   того же, что показывают виджеты.
2. **Пропущенный отчёт виден** — ритм считается по самой истории поступлений,
   и дыра в ряду называется датой, а не «данные неполные».
3. **«Показано на дашборде» учитывает все места**, где может стоять поле:
   иначе показатель, выведенный полосой «план-факт», числился бы забытым.
4. **Объекты сравниваются по ИМЕНАМ показателей**: коды граф у каждого объекта
   свои, и сравнение по кодам молча дало бы пустую таблицу.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db


@pytest.fixture
async def folder_with_data(ids):
    """Объект + папка + 5 недельных выпусков с пропуском одной недели."""
    async with db.acquire() as conn:
        await _drop(conn, ids["org"])
        oid = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,'ztest_an_obj') returning id", ids["org"])
        fid = await conn.fetchval(
            "insert into folders(organization_id,object_id,name) values($1,$2,'ztest_an_folder') returning id",
            ids["org"], oid)
        for code, name in (("plan", "Заявок принято"), ("fact", "Заявок исполнено")):
            await conn.execute(
                "insert into canonical_fields(object_id, code, name, data_type) values($1,$2,$3,'number') "
                "on conflict do nothing", oid, code, name)
        # Недели 01, 08, 15 и 29 — пропущена 22-я: ритм 7 дней, дыра видна.
        rel_ids = []
        for i, day in enumerate(("2026-06-01", "2026-06-08", "2026-06-15", "2026-06-29")):
            doc = await conn.fetchval(
                "insert into documents(organization_id, folder_id, original_filename, source_type, "
                "reporting_period_start, uploaded_by) values($1,$2,$3,'xlsx',$4::text::date,$5) returning id",
                ids["org"], fid, f"ztest_an_{i}.xlsx", day, ids["admin"])
            ver = await conn.fetchval(
                "insert into document_versions(document_id, version_no, storage_path, checksum, "
                "file_size_bytes, uploaded_by) values($1,1,$2,$3,1024,$4) returning id",
                doc, f"documents/ztest_an_{i}", f"ztest_sum_{i}", ids["admin"])
            rel = await conn.fetchval(
                "insert into dataset_releases(organization_id, code, name, status, reporting_period_start, "
                "created_by, object_id, source_document_version_id) "
                "values($1,'ztest_an_ds','Аналитика ДС','released',$2::text::date,$3,$4,$5) returning id",
                ids["org"], day, ids["admin"], oid, ver)
            rel_ids.append(rel)
            for code, base in (("plan", 100), ("fact", 90)):
                await conn.execute(
                    "insert into dataset_release_fields(dataset_release_id, canonical_field_code) "
                    "values($1,$2)", rel, code)
                await conn.execute(
                    "insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,value_number) "
                    "values($1,0,'Итого',$2,$3)", rel, code, base + i * 10)
    yield {"object_id": str(oid), "folder_id": str(fid), "org": ids["org"]}
    async with db.acquire() as conn:
        await _drop(conn, ids["org"])


async def _drop(conn, org_id):
    await conn.execute(
        "delete from dataset_values where dataset_release_id in "
        "(select id from dataset_releases where code like 'ztest_an%')")
    await conn.execute(
        "delete from dataset_release_fields where dataset_release_id in "
        "(select id from dataset_releases where code like 'ztest_an%')")
    await conn.execute("delete from dataset_releases where code like 'ztest_an%'")
    await conn.execute(
        "delete from document_versions where document_id in "
        "(select id from documents where original_filename like 'ztest_an%')")
    await conn.execute("delete from documents where original_filename like 'ztest_an%'")
    await conn.execute("delete from widgets where dashboard_id in "
                       "(select id from dashboards where name like 'ztest_an%')")
    await conn.execute("delete from dashboard_pages where dashboard_id in "
                       "(select id from dashboards where name like 'ztest_an%')")
    await conn.execute("delete from dashboards where name like 'ztest_an%'")
    await conn.execute("delete from folders where name like 'ztest_an%'")
    await conn.execute("delete from canonical_fields where object_id in "
                       "(select id from objects where name like 'ztest_an%')")
    await conn.execute("delete from objects where name like 'ztest_an%' and organization_id=$1", org_id)


async def test_summary_matches_active_release(client, admin_headers, folder_with_data):
    """Свод показывает значение последнего выпуска и прирост к предыдущему."""
    f = folder_with_data
    r = await client.get(f"/objects/{f['object_id']}/folders/{f['folder_id']}/analytics",
                         headers=admin_headers)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["data"]["periods"] == 4
    assert d["data"]["first_period"] == "2026-06-01" and d["data"]["last_period"] == "2026-06-29"

    plan = next(i for i in d["indicators"] if i["field"] == "plan")
    assert plan["value"] == 130, "берётся последний выпуск (100 + 3*10)"
    assert plan["prev_value"] == 120
    assert plan["delta"] == 10
    assert plan["name"] == "Заявок принято", "показатель называется по-человечески, а не кодом"


async def test_missing_report_is_named_by_date(client, admin_headers, folder_with_data):
    """Пропущенная неделя названа датой, а не общим «данные неполные»."""
    f = folder_with_data
    d = (await client.get(f"/objects/{f['object_id']}/folders/{f['folder_id']}/analytics",
                          headers=admin_headers)).json()
    assert d["data"]["cadence_days"] == 7, "ритм выводится из самой истории поступлений"
    assert "2026-06-22" in d["data"]["missing_periods"], d["data"]["missing_periods"]
    assert any(i["kind"] == "gaps" for i in d["data"]["issues"])


async def test_coverage_counts_plan_fact_fields(client, admin_headers, folder_with_data):
    """Поле, выведенное полосой «план-факт», считается показанным."""
    f = folder_with_data
    d = (await client.get(f"/objects/{f['object_id']}/folders/{f['folder_id']}/analytics",
                          headers=admin_headers)).json()
    assert d["coverage"]["shown_fields"] == 0, "дашбордов ещё нет — показано ноль"
    assert {m["field"] for m in d["coverage"]["missing_fields"]} == {"plan", "fact"}

    dash = await client.post("/dashboards", headers=admin_headers,
                             json={"name": "ztest_an_dash", "force": True})
    did = dash.json()["id"]
    await client.post(f"/dashboards/{did}/folder", headers=admin_headers, json={"folder_id": f["folder_id"]})
    page = await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "Обзор"})
    await client.post(f"/dashboard-pages/{page.json()['id']}/widgets", headers=admin_headers,
                      json={"name": "ztest_an План и факт", "widget_type": "plan_fact",
                            "config": {"dataset_code": "ztest_an_ds", "plan_field": "plan", "fact_field": "fact"}})

    d = (await client.get(f"/objects/{f['object_id']}/folders/{f['folder_id']}/analytics",
                          headers=admin_headers)).json()
    assert d["coverage"]["shown_fields"] == 2, "оба поля показаны — они внутри план-факта"
    assert d["coverage"]["missing_fields"] == []
    assert [x["name"] for x in d["coverage"]["dashboards"]] == ["ztest_an_dash"], \
        "дашборд папки должен быть назван"


async def test_objects_are_compared_by_indicator_names(client, admin_headers, folder_with_data, ids):
    """Второй объект со СВОИМИ кодами полей, но теми же названиями, попадает в сравнение."""
    f = folder_with_data
    async with db.acquire() as conn:
        oid2 = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,'ztest_an_obj2') returning id", ids["org"])
        # Коды у второго объекта ДРУГИЕ — как в жизни: они выводятся из
        # заголовков его собственной формы.
        for code, name in (("zayavki_prinyato", "Заявок принято"), ("zayavki_ispolneno", "Заявок исполнено")):
            await conn.execute(
                "insert into canonical_fields(object_id, code, name, data_type) values($1,$2,$3,'number')",
                oid2, code, name)
        rel = await conn.fetchval(
            "insert into dataset_releases(organization_id, code, name, status, reporting_period_start, "
            "created_by, object_id) values($1,'ztest_an_ds2','ДС2','released','2026-06-29',$2,$3) returning id",
            ids["org"], ids["admin"], oid2)
        for code, val in (("zayavki_prinyato", 500), ("zayavki_ispolneno", 480)):
            await conn.execute(
                "insert into dataset_release_fields(dataset_release_id, canonical_field_code) "
                "values($1,$2)", rel, code)
            await conn.execute(
                "insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,value_number) "
                "values($1,0,'Итого',$2,$3)", rel, code, val)
    try:
        d = (await client.get(f"/objects/{f['object_id']}/folders/{f['folder_id']}/analytics",
                              headers=admin_headers)).json()
        cmp = d["objects_compare"]
        names = {o["name"] for o in cmp["objects"]}
        assert {"ztest_an_obj", "ztest_an_obj2"} <= names, "оба объекта должны попасть в сравнение"
        assert "Заявок принято" in cmp["fields"]

        mine = next(o for o in cmp["objects"] if o["name"] == "ztest_an_obj")
        other = next(o for o in cmp["objects"] if o["name"] == "ztest_an_obj2")
        assert mine["is_current"] is True and other["is_current"] is False
        assert mine["values"]["Заявок принято"] == 130
        assert other["values"]["Заявок принято"] == 500, \
            "у второго объекта СВОИ коды полей — сопоставление идёт по названию"
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from dataset_values where dataset_release_id in "
                               "(select id from dataset_releases where code='ztest_an_ds2')")
            await conn.execute("delete from dataset_release_fields where dataset_release_id in "
                               "(select id from dataset_releases where code='ztest_an_ds2')")
            await conn.execute("delete from dataset_releases where code='ztest_an_ds2'")
            await conn.execute("delete from canonical_fields where object_id=$1", oid2)
            await conn.execute("delete from objects where id=$1", oid2)


async def test_analytics_is_closed_from_viewer(client, viewer, folder_with_data):
    f = folder_with_data
    r = await client.get(f"/objects/{f['object_id']}/folders/{f['folder_id']}/analytics",
                         headers=viewer["headers"])
    assert r.status_code == 403


async def test_folder_of_another_object_is_404(client, admin_headers, folder_with_data, ids):
    """Папку нельзя открыть «через» чужой объект — иначе адрес врал бы о принадлежности."""
    f = folder_with_data
    async with db.acquire() as conn:
        other = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,'ztest_an_other') returning id", ids["org"])
    try:
        r = await client.get(f"/objects/{other}/folders/{f['folder_id']}/analytics", headers=admin_headers)
        assert r.status_code == 404
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from objects where id=$1", other)


async def test_missing_field_can_be_added_to_dashboard(client, admin_headers, folder_with_data):
    """Забытый показатель добавляется карточкой, и покрытие сразу это видит.

    Список забытых показателей сам по себе — тупик: он сообщает о недостаче,
    а завести карточки предлагает вручную. Кнопка в аналитике делает то, ради
    чего человек в этот список и смотрит; здесь проверяется, что после
    добавления показатель перестаёт числиться забытым.
    """
    f = folder_with_data
    dash = await client.post("/dashboards", headers=admin_headers,
                             json={"name": "ztest_an_add", "force": True})
    did = dash.json()["id"]
    await client.post(f"/dashboards/{did}/folder", headers=admin_headers, json={"folder_id": f["folder_id"]})
    page = await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "Обзор"})
    pid = page.json()["id"]

    before = (await client.get(f"/objects/{f['object_id']}/folders/{f['folder_id']}/analytics",
                               headers=admin_headers)).json()
    missing = before["coverage"]["missing_fields"]
    assert len(missing) == 2, "оба показателя пока нигде не показаны"

    # Ровно то, что делает кнопка: карточка на выбранную страницу.
    r = await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                          json={"name": missing[0]["name"], "widget_type": "kpi",
                                "config": {"dataset_code": "ztest_an_ds", "value_field": missing[0]["field"]},
                                "position_x": 0, "position_y": 999, "width": 4, "height": 5})
    assert r.status_code in (200, 201), r.text

    after = (await client.get(f"/objects/{f['object_id']}/folders/{f['folder_id']}/analytics",
                              headers=admin_headers)).json()
    assert after["coverage"]["shown_fields"] == 1
    assert [m["field"] for m in after["coverage"]["missing_fields"]] == [missing[1]["field"]], \
        "добавленный показатель обязан исчезнуть из забытых"
