"""Досоздать объявления граф у выпусков, записанных мимо штатного выпуска.

Находка 23.09.2026: недельные выпуски 12 ведомств «Статистики услуг» писал
скрипт `tools/dnr_stats/load_weekly_file.py`, и он не объявлял графы выпуска
(`dataset_release_fields`). Значения при этом на месте, раздел «Статистика
услуг» работает (он читает значения напрямую), но мастер сборки и подсказки
виджетов видят у таких выпусков НОЛЬ граф и отвечают «нет числовых полей».

Инструмент делает две вещи, обе — тем же кодом приложения:
  1. объявляет графы у выпусков без объявления (`mapping.declare_release_fields`);
  2. переводит в «число» графы справочника, заведённые текстом, если во всех
     выпусках объекта в них лежат только числа. Тип графы — догадка, её
     значения — факт; мастер берёт графы с типом `number`.

Значения выпусков НЕ трогаются. Повторный запуск ничего не меняет.

Запуск внутри контейнера api (там есть приложение и доступ к БД):
    docker cp tools/maintenance/backfill_release_fields.py dashbord_api:/tmp/
    docker exec -w /app -e PYTHONPATH=/app dashbord_api python3 /tmp/backfill_release_fields.py          # показать
    docker exec -w /app -e PYTHONPATH=/app dashbord_api python3 /tmp/backfill_release_fields.py --apply  # сделать
На боевом — тот же путь, контейнер `dashbord_prod_api`.
"""
import asyncio
import sys

import asyncpg

from app.config import settings
from app.modules.ingestion import mapping

APPLY = "--apply" in sys.argv

# Текстовая графа, в которой во всех выпусках объекта лежат только числа.
_TEXT_BUT_NUMBERS = """
select cf.object_id, cf.code, o.name as object_name,
       count(v.*) as filled
from canonical_fields cf
join objects o on o.id = cf.object_id
join dataset_releases r on r.object_id = cf.object_id
join dataset_values v on v.dataset_release_id = r.id and v.canonical_field_code = cf.code
where cf.data_type = 'text' and not cf.is_row_label
  -- Графа без имени («Столбец 293») — пустой хвост бланка, а не показатель:
  -- числом она всплыла бы в мастере бессмысленной карточкой.
  and cf.name !~ '^Столбец [0-9]+$'
group by cf.object_id, cf.code, o.name
having count(*) filter (where v.value_number is null and coalesce(trim(v.value_text), '') <> '') = 0
   and count(*) filter (where v.value_number is not null) > 0
"""


async def main() -> None:
    conn = await asyncpg.connect(settings.database_dsn)
    try:
        bare = await conn.fetch(
            "select r.id, r.code, r.reporting_period_start as p, r.status from dataset_releases r "
            "where not exists (select 1 from dataset_release_fields f where f.dataset_release_id = r.id) "
            "  and exists (select 1 from dataset_values v where v.dataset_release_id = r.id) "
            "order by r.code, r.reporting_period_start")
        wrong_type = await conn.fetch(_TEXT_BUT_NUMBERS)

        print(f"Выпусков без объявленных граф: {len(bare)}")
        by_code: dict[str, int] = {}
        for r in bare:
            by_code[r["code"]] = by_code.get(r["code"], 0) + 1
        for code, n in sorted(by_code.items()):
            print(f"  {code}: {n}")
        print(f"Текстовых граф, в которых только числа: {len(wrong_type)}")
        by_obj: dict[str, int] = {}
        for w in wrong_type:
            by_obj[w["object_name"]] = by_obj.get(w["object_name"], 0) + 1
        for name, n in sorted(by_obj.items()):
            print(f"  {name}: {n}")

        if not APPLY:
            print("\nНичего не изменено. Чтобы исправить, запустите с --apply.")
            return

        async with conn.transaction():
            added = 0
            for r in bare:
                added += await mapping.declare_release_fields(conn, r["id"])
            for w in wrong_type:
                await conn.execute(
                    "update canonical_fields set data_type='number' where object_id=$1 and code=$2",
                    w["object_id"], w["code"])
        print(f"\nГотово: объявлено граф {added} у {len(bare)} выпусков; "
              f"тип «число» проставлен {len(wrong_type)} графам.")
    finally:
        await conn.close()


asyncio.run(main())
