# -*- coding: utf-8 -*-
"""Временная форма для съёмки этапа 5 (shoot_v11.js). Запуск внутри контейнера api.

    base   — объект и первый отчёт формы (печатает id объекта);
    news   — второй отчёт с новыми графами и объявление (как после ручного выпуска);
    clean  — убрать всё, что заводилось.

Имена правдоподобные: в руководство служебные «ztest» попасть не должны.
Уборка — по точному имени объекта и коду формы.
"""
import asyncio
import os
import sys
from datetime import date

sys.path.insert(0, "/app")
import asyncpg  # noqa: E402

from app.modules.ingestion import new_fields as nf  # noqa: E402

CODE = "doc_zapis_week"
OBJ = "Запись на приём — недельная сводка"
BASE = {"obr": ("Принято заявлений", [412, 385, 297]), "ved": ("Выдано результатов", [398, 371, 280])}
NEWS = {"zap": ("Записались через МАХ", [0, 14, 6]), "otk": ("Отказано в приёме", [3, 1, 0])}
ROWS = ["Отделение № 1 г. Донецк", "Отделение № 2 г. Макеевка", "Отделение № 3 г. Горловка"]


async def rel(conn, org, admin, oid, period, fields):
    rid = await conn.fetchval(
        "insert into dataset_releases(organization_id,code,name,status,reporting_period_start,created_by,"
        "object_id) values($1,$2,$3,'validated',$4,$5,$6) returning id",
        org, CODE, OBJ, period, admin, oid)
    for code, (name, vals) in fields.items():
        await conn.execute(
            "insert into canonical_fields(object_id,code,name,data_type,created_by) values($1,$2,$3,'number',$4) "
            "on conflict (object_id,code) do update set name=excluded.name", oid, code, name, admin)
        for i, v in enumerate(vals):
            await conn.execute(
                "insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,"
                "value_number) values($1,$2,$3,$4,$5)", rid, i, ROWS[i], code, v)
        await conn.execute(
            "insert into dataset_release_fields(dataset_release_id,canonical_field_code) values($1,$2)", rid, code)


async def clean(conn):
    oid = await conn.fetchval("select id from objects where name=$1", OBJ)
    if oid:
        await conn.execute(
            "delete from notification_recipients where notification_event_id in (select id from "
            "notification_events where entity_type='object' and entity_id=$1)", oid)
        await conn.execute("delete from notification_events where entity_type='object' and entity_id=$1", oid)
    await conn.execute("delete from dataset_new_fields where code=$1", CODE)
    await conn.execute("delete from dataset_values where dataset_release_id in "
                       "(select id from dataset_releases where code=$1)", CODE)
    await conn.execute("delete from dataset_release_fields where dataset_release_id in "
                       "(select id from dataset_releases where code=$1)", CODE)
    await conn.execute("delete from dataset_releases where code=$1", CODE)
    if oid:
        await conn.execute("delete from canonical_fields where object_id=$1", oid)
        await conn.execute("delete from objects where id=$1", oid)


async def main():
    conn = await asyncpg.connect(
        host=os.environ["POSTGRES_HOST"], port=int(os.environ["POSTGRES_PORT"]),
        user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"],
        database=os.environ["POSTGRES_DB"])
    org = await conn.fetchval("select id from organizations order by created_at limit 1")
    admin = await conn.fetchval("select id from users where login='admin'")
    step = sys.argv[1]
    if step == "clean":
        await clean(conn)
    elif step == "base":
        await clean(conn)
        oid = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,$2) returning id", org, OBJ)
        await rel(conn, org, admin, oid, date(2026, 9, 22), BASE)
        print(oid)
    elif step == "news":
        oid = await conn.fetchval("select id from objects where name=$1", OBJ)
        await rel(conn, org, admin, oid, date(2026, 9, 29), {**BASE, **NEWS})
        res = await nf.announce(conn, org, CODE)
        print("объявлено:", [f["name"] for f in res["fields"]] if res else None,
              "уведомление:", bool(res and res["notice_id"]))
    await conn.close()


asyncio.run(main())
