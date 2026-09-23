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

  3. дописывает в шаблоны разметки ПОДПИСИ снятых строк (`skip_labels`), если
     их там ещё нет: с 23.09.2026 снятые строки переносятся на выросшую форму
     по подписи, а шаблоны, сохранённые раньше, знали только номера строк.
     Подписи берутся из того самого листа, с которого сохранён шаблон.

Значения выпусков НЕ трогаются. Повторный запуск ничего не меняет.

Запуск внутри контейнера api (там есть приложение и доступ к БД):
    docker cp tools/maintenance/backfill_release_fields.py dashbord_api:/tmp/
    docker exec -w /app -e PYTHONPATH=/app dashbord_api python3 /tmp/backfill_release_fields.py          # показать
    docker exec -w /app -e PYTHONPATH=/app dashbord_api python3 /tmp/backfill_release_fields.py --apply  # сделать
На боевом — тот же путь, контейнер `dashbord_prod_api`.
"""
import asyncio
import json
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


async def _template_skip_labels(conn) -> dict:
    """{object_id: (имя объекта, подписи снятых строк)} для шаблонов без подписей."""
    out: dict = {}
    rows = await conn.fetch(
        "select t.object_id, o.name, t.layout, t.fields, t.source_release_id from object_layout_templates t "
        "join objects o on o.id = t.object_id "
        "where t.mode = 'table' and not (t.layout ? 'skip_labels') "
        "  and jsonb_array_length(coalesce(t.layout->'skip_rows', '[]'::jsonb)) > 0")
    for t in rows:
        # Лист шаблона — тот, чьи распознанные столбцы привязаны к выпуску-источнику.
        table = await conn.fetchrow(
            "select et.data, et.merges, et.header_rows from dataset_release_fields f "
            "join extracted_columns ec on ec.id = f.extracted_column_id "
            "join extracted_tables et on et.id = ec.extracted_table_id "
            "where f.dataset_release_id = $1 limit 1", t["source_release_id"])
        if table is None:
            continue
        lay = json.loads(t["layout"]) if isinstance(t["layout"], str) else t["layout"]
        fields = json.loads(t["fields"]) if isinstance(t["fields"], str) else t["fields"]
        grid = json.loads(table["data"]) if isinstance(table["data"], str) else table["data"]
        merges = [tuple(m) for m in (json.loads(table["merges"]) if isinstance(table["merges"], str)
                                     else table["merges"] or [])]
        area = mapping.analysis_grid(grid, merges, lay.get("data_rect"),
                                     lay.get("orientation") or "columns")
        col = next((f.get("column_index") for f in fields if f.get("is_row_label")), None)
        if col is None:
            continue
        labels = sorted({str(area[i][col]).strip() for i in lay["skip_rows"]
                         if i < len(area) and col < len(area[i])})
        out[t["object_id"]] = (t["name"], labels)
    return out


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

        tpl_labels = await _template_skip_labels(conn)
        print(f"Шаблонов, куда можно дописать подписи снятых строк: {len(tpl_labels)}")
        for name, labels in tpl_labels.values():
            print(f"  {name}: {len(labels)} подписей, напр. {labels[:3]}")

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
            for object_id, (_name, labels) in tpl_labels.items():
                await conn.execute(
                    "update object_layout_templates set layout = layout || jsonb_build_object("
                    "'skip_labels', $2::jsonb) where object_id=$1",
                    object_id, json.dumps(labels, ensure_ascii=False))
        print(f"\nГотово: объявлено граф {added} у {len(bare)} выпусков; "
              f"тип «число» проставлен {len(wrong_type)} графам.")
    finally:
        await conn.close()


asyncio.run(main())
