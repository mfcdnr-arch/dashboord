# -*- coding: utf-8 -*-
"""Временная форма-реестр для съёмки главы о подсчёте строк (shoot_v12.js).

Запуск внутри контейнера api:
    base  — объект и один отчёт реестра проблемных вопросов (печатает id объекта);
    clean — убрать всё, что заводилось.

Форма учебная и названа так, чтобы её нельзя было принять за настоящую:
настоящий лист «Проблемные вопросы» формы Минэкономразвития пока пуст, а
матрицу рисков и счётчики в руководстве нужно показать с числами. Уборка —
по точному имени объекта и коду формы.
"""
import asyncio
import os
import sys
from datetime import date

sys.path.insert(0, "/app")
import asyncpg  # noqa: E402

CODE = "doc_reestr_voprosov"
OBJ = "Реестр вопросов — учебный пример"
FIELDS = [("status", "Статус", "text"), ("uroven_riska", "Уровень риска", "text"),
          ("ocenka_riska", "Оценка риска", "number"),
          ("veroyatnost", "Вероятность недостижения решения", "number"),
          ("vliyanie", "Влияние", "number"), ("srok_resheniya", "Срок решения", "text"),
          ("otvetstvennyy", "Ответственный", "text")]
# Наименование | статус | уровень | оценка | вероятность | влияние | срок | ответственный
ROWS = [
    ("Вопрос 1. Замена терминалов электронной очереди", "В работе", "Высокий", 16, 4, 4,
     "15.09.2026", "Отдел ИТ"),
    ("Вопрос 2. Помещение для нового отделения", "В работе", "Высокий", 20, 4, 5,
     "до 30.10.2026", "Отдел развития"),
    ("Вопрос 3. Подключение к сети передачи данных", "В работе", "Средний", 9, 3, 3,
     "01.10.2026", "Отдел ИТ"),
    ("Вопрос 4. Обучение работников новым услугам", "В работе", "Средний", 12, 3, 4,
     "20.11.2026", "Учебный центр"),
    ("Вопрос 5. Режим работы выездных отделений", "В работе", "Низкий", 6, 2, 3,
     "на постоянной основе", "Отдел организации работы"),
    ("Вопрос 6. Согласование проектной документации", "В работе", "Средний", 8, 2, 4,
     "28.09.2026", "Отдел развития"),
    ("Вопрос 7. Поставка расходных материалов", "Вопрос решен", "Снят", 2, 1, 2,
     "10.09.2026", "Хозяйственный отдел"),
    ("Вопрос 8. Изменение порядка приёма документов", "Не актуально", "Не актуально", 3, 1, 3,
     "", "Отдел организации работы"),
]


async def clean(conn):
    oid = await conn.fetchval("select id from objects where name=$1", OBJ)
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
    if sys.argv[1] == "clean":
        await clean(conn)
    else:
        await clean(conn)
        oid = await conn.fetchval("insert into objects(organization_id,name) values($1,$2) returning id", org, OBJ)
        for code, name, dt in FIELDS:
            await conn.execute(
                "insert into canonical_fields(object_id,code,name,data_type,created_by) values($1,$2,$3,$4,$5)",
                oid, code, name, dt, admin)
        rid = await conn.fetchval(
            "insert into dataset_releases(organization_id,code,name,status,reporting_period_start,created_by,"
            "object_id) values($1,$2,'Проблемные вопросы (учебный пример)','validated',$3,$4,$5) returning id",
            org, CODE, date(2026, 10, 6), admin, oid)
        for i, (label, *vals) in enumerate(ROWS):
            for (code, _n, dt), v in zip(FIELDS, vals, strict=True):
                col = "value_number" if dt == "number" else "value_text"
                await conn.execute(
                    f"insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,{col}) "
                    "values($1,$2,$3,$4,$5)", rid, i, label, code, v)
        for code, _n, _dt in FIELDS:
            await conn.execute(
                "insert into dataset_release_fields(dataset_release_id,canonical_field_code) values($1,$2)", rid, code)
        print(oid)
    await conn.close()


asyncio.run(main())
