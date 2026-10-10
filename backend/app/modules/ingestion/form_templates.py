"""Шаблоны разметки ФОРМ: единственное место, где читается и пишется
`object_layout_templates` (с 09.10.2026, миграция 061).

Шаблон раньше был один на объект, и прямые запросы `where object_id = $1`
жили в пяти модулях. С переходом на шаблон «объект + код набора» каждый такой
запрос молча стал бы неверным: `fetchrow` вернул бы произвольную форму из
нескольких, а `update … where object_id` записал бы ступени одного листа во
все. Поэтому доступ собран здесь, а страж `test_form_templates_access` не даёт
завести запрос к таблице мимо этого модуля.

Транзакции — снаружи, как и у остального конвейера.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

COLS = (
    "t.object_id, t.dataset_code, t.sheet_name, t.fingerprint, t.mode, t.layout, t.fields, "
    "t.cells, t.row_count, t.headers, t.levels, t.source_release_id, t.updated_at"
)
# Тот же набор граф шаблона для переноса в историю и обратно.
_HIST_COLS = ("object_id, fingerprint, mode, layout, fields, cells, row_count, dataset_code, "
              "source_release_id, headers, levels, sheet_name")


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


async def get(conn, object_id, code: str):
    """Шаблон формы `code` объекта; None — форма ещё не размечена."""
    return await conn.fetchrow(
        f"select {COLS}, r.name as release_name, r.reporting_period_start as release_period "
        "from object_layout_templates t left join dataset_releases r on r.id = t.source_release_id "
        "where t.object_id = $1::uuid and t.dataset_code = $2", str(object_id), code)


async def for_object(conn, object_id) -> List[Any]:
    """Все формы объекта — в порядке, в каком их листы идут в книге (по имени
    листа нельзя, по коду — машинно), затем по коду."""
    return await conn.fetch(
        f"select {COLS}, r.name as release_name, r.reporting_period_start as release_period "
        "from object_layout_templates t left join dataset_releases r on r.id = t.source_release_id "
        "left join extracted_tables et on et.id = ("
        "  select et2.id from extracted_tables et2 "
        "  join extraction_jobs j on j.id = et2.extraction_job_id "
        "  where j.document_version_id = r.source_document_version_id "
        "    and et2.sheet_or_page is not distinct from t.sheet_name limit 1) "
        "where t.object_id = $1::uuid "
        "order by et.table_index nulls last, t.dataset_code", str(object_id))


async def only(conn, object_id):
    """Шаблон, если у объекта он ЕДИНСТВЕННЫЙ; иначе None.

    Для мест, где форма не названа: угадывать одну из нескольких нельзя —
    ступени, лестница и подсказки одного листа на другом были бы правдоподобны
    и неверны.
    """
    rows = await for_object(conn, object_id)
    return rows[0] if len(rows) == 1 else None


async def for_org(conn, org_id) -> List[Any]:
    """Все шаблоны организации с именем объекта — для узнавания файла из общей
    зоны загрузки и списка «Уже узнаются сами»."""
    return await conn.fetch(
        f"select {COLS}, o.name as object_name "
        "from object_layout_templates t join objects o on o.id = t.object_id "
        "where o.organization_id = $1 order by o.name, t.dataset_code", org_id)


async def codes_with_template(conn, object_id) -> List[str]:
    rows = await conn.fetch(
        "select dataset_code from object_layout_templates where object_id = $1::uuid", str(object_id))
    return [r["dataset_code"] for r in rows]


async def save(conn, *, object_id, code: str, sheet_name: Optional[str], fingerprint: str,
               mode: str, layout: dict, fields: List[dict], cells: List[dict], row_count: int,
               release_id, user_id, headers: Optional[List[str]] = None,
               reason: Optional[str] = None) -> bool:
    """Запомнить разметку последнего выпуска ФОРМЫ.

    Возвращает True, если шаблон этой формы заведён впервые (`xmax = 0` верно
    ровно для строки, вставленной этой командой, включая ветку `on conflict`):
    по нему экран выпуска один раз спрашивает, что вынести на «Главную».

    Прежний шаблон уходит в историю, только если сменилась СТРУКТУРА формы.
    Соседние формы объекта не трогаются вовсе — раньше выпуск «Итогов недели»
    затирал разметку «Показателей», и книга узнавалась по одному листу.
    """
    await conn.execute(
        f"insert into object_layout_template_history({_HIST_COLS}, valid_from, replaced_by, replaced_reason) "
        f"select {_HIST_COLS}, updated_at, $3, $5 from object_layout_templates "
        "where object_id = $1 and dataset_code = $2 and fingerprint <> $4",
        object_id, code, user_id, fingerprint, reason or "разметку заменил новый выпуск")
    row = await conn.fetchrow(
        "insert into object_layout_templates(object_id, dataset_code, sheet_name, fingerprint, mode, "
        "layout, fields, cells, row_count, source_release_id, updated_by, updated_at, headers) "
        "values($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8::jsonb,$9,$10,$11,now(),$12::jsonb) "
        "on conflict (object_id, dataset_code) do update set sheet_name=excluded.sheet_name, "
        "fingerprint=excluded.fingerprint, mode=excluded.mode, layout=excluded.layout, "
        "fields=excluded.fields, cells=excluded.cells, row_count=excluded.row_count, "
        "source_release_id=excluded.source_release_id, updated_by=excluded.updated_by, "
        "updated_at=now(), headers=excluded.headers "
        "returning (xmax = 0) as inserted",
        object_id, code, sheet_name, fingerprint, mode, _dump(layout), _dump(fields), _dump(cells),
        int(row_count or 0), release_id, user_id, _dump(list(headers or [])),
    )
    return bool(row["inserted"])


async def set_levels(conn, object_id, code: str, levels: dict) -> bool:
    """Подтверждённые ступени — в шаблон ЭТОЙ формы. False — шаблона нет."""
    res = await conn.execute(
        "update object_layout_templates set levels = $3::jsonb, updated_at = now() "
        "where object_id = $1::uuid and dataset_code = $2", str(object_id), code, _dump(levels))
    return res.endswith(" 1")


async def patch_layout(conn, object_id, code: str, patch: dict) -> None:
    """Дописать ключи разметки (инструменты обслуживания: подписи снятых строк)."""
    await conn.execute(
        "update object_layout_templates set layout = layout || $3::jsonb "
        "where object_id = $1::uuid and dataset_code = $2", str(object_id), code, _dump(patch))


async def history(conn, object_id) -> Dict:
    """Действующие шаблоны форм объекта и прежние — для экрана объекта."""
    from ..dashboards._suggest import form_title  # локально: dashboards тянет ingestion

    def _row(r) -> dict:
        fields = r["fields"]
        headers = r["headers"]
        fields = json.loads(fields) if isinstance(fields, str) else (fields or [])
        headers = json.loads(headers) if isinstance(headers, str) else (headers or [])
        return {
            "dataset_code": r["dataset_code"],
            "sheet_name": r["sheet_name"],
            "fields": len(fields),
            "headers": len(headers),
            "period": r["release_period"].isoformat() if r["release_period"] else None,
        }

    cur = await for_object(conn, object_id)
    titles: Dict[str, str] = {}
    for r in cur:
        last = await conn.fetchval(
            "select name from dataset_releases where object_id = $1::uuid and code = $2 "
            "and status <> 'superseded' order by reporting_period_start desc nulls last, "
            "created_at desc limit 1", str(object_id), r["dataset_code"])
        titles[r["dataset_code"]] = r["sheet_name"] or (form_title(last) if last else r["dataset_code"])
    hist = await conn.fetch(
        "select h.*, r.reporting_period_start as release_period, u.login as replaced_by_login "
        "from object_layout_template_history h "
        "left join dataset_releases r on r.id = h.source_release_id "
        "left join users u on u.id = h.replaced_by "
        "where h.object_id = $1::uuid order by h.replaced_at desc limit 30", str(object_id))
    templates = [{**_row(r), "title": titles.get(r["dataset_code"]) or r["dataset_code"],
                  "updated_at": r["updated_at"].isoformat()} for r in cur]
    return {
        "templates": templates,
        # Прежний контракт (один действующий шаблон) — для объектов с одной формой.
        "current": templates[0] if len(templates) == 1 else None,
        "history": [{**_row(h), "id": str(h["id"]), "replaced_at": h["replaced_at"].isoformat(),
                     "replaced_by": h["replaced_by_login"], "reason": h["replaced_reason"],
                     "title": titles.get(h["dataset_code"]) or h["sheet_name"] or h["dataset_code"]}
                    for h in hist],
    }


async def restore(conn, object_id, history_id: str, user_id) -> str:
    """Вернуть прежний шаблон ЕГО формы. Действующий шаблон этой формы (если
    есть) уходит в историю; соседние формы не трогаются. Возвращает код формы."""
    h = await conn.fetchrow(
        "select * from object_layout_template_history where id = $1::uuid and object_id = $2::uuid",
        history_id, str(object_id))
    if h is None:
        raise LookupError("Прежний шаблон не найден")
    if not h["dataset_code"]:
        raise LookupError("У прежнего шаблона не записан код формы — вернуть его некуда")
    await conn.execute(
        f"insert into object_layout_template_history({_HIST_COLS}, valid_from, replaced_by, replaced_reason) "
        f"select {_HIST_COLS}, updated_at, $3, 'вместо него возвращён прежний шаблон' "
        "from object_layout_templates where object_id = $1 and dataset_code = $2",
        h["object_id"], h["dataset_code"], user_id)
    await conn.execute(
        "insert into object_layout_templates(object_id, dataset_code, sheet_name, fingerprint, mode, "
        "layout, fields, cells, row_count, source_release_id, headers, levels, updated_by, updated_at) "
        "values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,now()) "
        "on conflict (object_id, dataset_code) do update set sheet_name=excluded.sheet_name, "
        "fingerprint=excluded.fingerprint, mode=excluded.mode, layout=excluded.layout, "
        "fields=excluded.fields, cells=excluded.cells, row_count=excluded.row_count, "
        "source_release_id=excluded.source_release_id, headers=excluded.headers, "
        "levels=excluded.levels, updated_by=excluded.updated_by, updated_at=now()",
        h["object_id"], h["dataset_code"], h["sheet_name"], h["fingerprint"], h["mode"],
        h["layout"], h["fields"], h["cells"], h["row_count"], h["source_release_id"],
        h["headers"], h["levels"], user_id)
    await conn.execute("delete from object_layout_template_history where id = $1", h["id"])
    return h["dataset_code"]


async def forget(conn, object_id, code: str, user_id) -> bool:
    """Перестать узнавать форму: шаблон уходит в историю (его можно вернуть).

    Нужно, потому что ошибочный выпуск под НОВЫМ кодом теперь не вытесняет
    чужой шаблон, а заводит свой — и без этой кнопки он навсегда участвовал бы
    в узнавании файлов, а убрать его можно было бы только правкой базы.
    """
    moved = await conn.execute(
        f"insert into object_layout_template_history({_HIST_COLS}, valid_from, replaced_by, replaced_reason) "
        f"select {_HIST_COLS}, updated_at, $3, 'форму перестали узнавать (шаблон снят вручную)' "
        "from object_layout_templates where object_id = $1::uuid and dataset_code = $2",
        str(object_id), code, user_id)
    if not moved.endswith(" 1"):
        return False
    await conn.execute(
        "delete from object_layout_templates where object_id = $1::uuid and dataset_code = $2",
        str(object_id), code)
    return True


async def known(conn, org_id) -> List[Any]:
    """Шаблоны организации с папкой назначения и числом загруженных отчётов —
    для списка «Уже узнаются сами» на «📥 Загрузке».

    Папка считается ТЕМ ЖЕ правилом, что реальная маршрутизация: сперва папка
    документа-источника шаблона, а если он уже удалён — любая обычная папка
    объекта. Иначе подсказка сказала бы «некуда» там, где загрузка сработает.
    """
    return await conn.fetch(
        "select t.object_id, o.name as object_name, t.dataset_code, t.sheet_name, t.updated_at, "
        "  t.row_count, doc.original_filename as example_filename, "
        "  coalesce(fr.name, ff.name) as folder_name, "
        "  (select count(*) from dataset_releases r2 "
        "   where r2.code = t.dataset_code and r2.status <> 'superseded') as periods_loaded "
        "from object_layout_templates t "
        "join objects o on o.id = t.object_id "
        "left join dataset_releases rel on rel.id = t.source_release_id "
        "left join document_versions v on v.id = rel.source_document_version_id "
        "left join documents doc on doc.id = v.document_id "
        "left join folders fr on fr.id = doc.folder_id "
        "left join lateral ("
        "  select f.name from folders f where f.object_id = t.object_id and not f.is_inbox "
        "  order by f.auto_prepare desc, f.created_at limit 1"
        ") ff on fr.id is null "
        "where o.organization_id = $1 "
        "order by o.name, t.dataset_code", org_id)
