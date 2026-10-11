"""Ступени формы: предложение системы и то, что подтвердил человек.

Распознавание (`ingestion.hierarchy`) — чистое правило на именах граф. Здесь
оно встречается с данными объекта: сколько у каждого значения объёма, что
уходит в узел «Отдельные услуги» и что из этого человек уже подтвердил.

🔴 Имена уровням система НЕ придумывает, и это решение, а не пробел. Надёжного
источника для них в данных нет: у РЦО столбец меток строк называется
«Наименование услуги · Наименование отдела МФЦ», у «Статистики услуг» — «МФЦ
(адрес)», у формы окон — «Наименование отделения». Угадать «Ведомство» и
«Услуга» отсюда нельзя, а подсунуть человеку правдоподобное имя, которое он
подтвердит не глядя, хуже пустого поля: имя уровня потом попадает в текст
интерфейса («источник не даёт разбивки по уровню „Услуга"»).

Вместо угадывания мастер показывает ЗНАЧЕНИЯ ступени — увидев «Росреестр, МВД,
ЕСИА (260), ЗАГС (377)», человек называет уровень сам за секунду.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..ingestion.hierarchy import KIND_HIERARCHY, detect_levels, group_lone, split_segments

# Сколько значений ступени показать в мастере как образец: по ним человек
# понимает, что за уровень перед ним. Больше — стена текста, меньше — не видно
# разнообразия.
SAMPLE = 6

# Мера, выбранная по умолчанию (решение заказчика 09.09: «по умолчанию
# Принято»). Сравниваем по началу имени: у РЦО мера зовётся «Принято, ед.», у
# «Статистики услуг» — просто «Принято».
DEFAULT_MEASURE_PREFIX = "принято"


async def _fields_with_volume(conn, object_id, code: Optional[str] = None) -> List[dict]:
    """Графы объекта с объёмом по ВСЕЙ истории выпусков.

    Объём нужен, чтобы отделить одинокие значения от крупных. Берём всю
    историю, а не последний отчёт: у «Администрации м.о. Горловка» десять услуг
    и ноль обращений за 31.08 — по одному дню она выглядит пустышкой, хотя это
    настоящее ведомство. Тот же урок уже стоил правки при отборе показателей.
    """
    rows = await conn.fetch(
        "select cf.name, coalesce(sum(abs(v.value_number)), 0) as volume, "
        "count(v.value_number) as numbers "
        "from canonical_fields cf "
        "left join dataset_values v on v.canonical_field_code = cf.code "
        "left join dataset_releases r on r.id = v.dataset_release_id and r.status <> 'superseded' "
        "  and ($2::text is null or r.code = $2) "
        "where cf.object_id = $1 "
        # У книги из нескольких форм справочник граф общий на объект: ступени
        # одной формы считаем по графам, объявленным в ЕЁ выпусках.
        "  and ($2::text is null or exists (select 1 from dataset_release_fields rf "
        "       join dataset_releases r2 on r2.id = rf.dataset_release_id "
        "       where r2.object_id = $1 and r2.code = $2 and rf.canonical_field_code = cf.code)) "
        "group by cf.name",
        object_id, code,
    )
    return [dict(r) for r in rows]


async def _row_sample(conn, object_id, code: Optional[str] = None) -> Dict:
    """Строки формы — самая мелкая ступень: сколько их и как они выглядят."""
    rows = await conn.fetch(
        "select distinct v.row_label from dataset_values v "
        "join dataset_releases r on r.id = v.dataset_release_id "
        "where r.object_id = $1 and r.status <> 'superseded' and ($2::text is null or r.code = $2) "
        "and v.row_label is not null and v.row_label <> '' order by v.row_label",
        object_id, code,
    )
    labels = [r["row_label"] for r in rows]
    return {"count": len(labels), "sample": labels[:SAMPLE]}


async def suggest(conn, object_id, code: Optional[str] = None) -> Dict:
    """Что система предлагает считать ступенями этой формы."""
    fields = await _fields_with_volume(conn, object_id, code)
    if not fields:
        return {"kind": "unknown", "levels": [], "rows": {"count": 0, "sample": []},
                "reason": "По этому объекту ещё нет выпущенных данных — "
                          "разберём форму, когда появится первый выпуск."}

    # 🔴 Ступени строим по ВСЕМ графам, а тип столбца не спрашиваем вовсе.
    # Первая версия отсеивала графы с `data_type = text`, считая их метками и
    # комментариями, — и это оказалось прямой потерей данных. Замер: у формы
    # «Статистика услуг — МВД» 118 граф вида «Услуга N: Принято» определены
    # текстовыми (в образце строк стояло «нет» или пусто), но лежит в них
    # 34 148 ЧИСЕЛ. Фильтр по типу выбрасывал 21 услугу из 29 и большую часть
    # данных ведомства; на РЦО он же терял настоящее ведомство «ООО Правовое
    # бюро Центр долговых решений».
    #
    # Тип столбца — догадка распознавания по образцу, а устройство имени —
    # факт. Поэтому в ступени пускаем всё, у чего есть разделитель, а к типу
    # обращаемся только там, где он действительно нужен: мерой не может быть
    # графа, в которой нет ни одного числа (см. ниже).
    numeric = fields
    res = detect_levels([f["name"] for f in numeric])
    rows = await _row_sample(conn, object_id, code)

    # Мера — то, что можно измерить: графа без единого числа мерой не бывает.
    # Так из списка уходят «Комментарии по офисам» и «Приоритетная услуга», но
    # остаются «Принято» и «Выдано» тех услуг, чей тип распознан неверно.
    with_numbers = {f["name"] for f in fields if int(f["numbers"] or 0) > 0}
    measured_tails = {
        split_segments(n, res["separator"])[-1]
        for n in with_numbers
        if res["separator"] and len(split_segments(n, res["separator"])) >= 2
    } if res["separator"] else set()
    measures = [m for m in res.get("measures", []) if m in measured_tails]

    out: Dict = {"kind": res["kind"], "separator": res["separator"],
                 "reason": res["reason"], "measures": measures,
                 "rows": rows, "levels": []}
    if res["kind"] != KIND_HIERARCHY:
        return out

    # Объём и наличие подступени — по каждому значению ПЕРВОЙ ступени: по ним
    # решается, что уходит в узел «Отдельные услуги».
    sep = res["separator"]
    first = res["levels"][0]["values"]
    vol: Dict[str, float] = {}
    kids: Dict[str, bool] = {}
    for f in numeric:
        segs = split_segments(f["name"], sep)
        if len(segs) < 2 or segs[0] not in first:
            continue
        vol[segs[0]] = vol.get(segs[0], 0.0) + float(f["volume"] or 0)
        kids[segs[0]] = kids.get(segs[0], False) or len(segs) > 2

    grouped = group_lone([{"value": v, "volume": vol.get(v, 0.0),
                           "has_children": kids.get(v, False)} for v in first])
    out["group"] = {"rows": len(grouped["rows"]), "lone": [i["value"] for i in grouped["lone"]],
                    "reason": grouped["reason"],
                    "sample": [r["value"] for r in grouped["rows"][:SAMPLE]]}

    for lv in res["levels"]:
        out["levels"].append({"index": lv["index"], "count": lv["count"],
                              "sample": lv["values"][:SAMPLE], "name": ""})

    out["measure_default"] = next(
        (m for m in measures if m.lower().startswith(DEFAULT_MEASURE_PREFIX)),
        measures[0] if measures else None)
    return out


async def _template(conn, object_id, code: Optional[str]):
    """Шаблон формы, к которой относятся ступени.

    С 09.10.2026 шаблон хранится на форму (объект + код). Код не назван —
    берём шаблон, только если форма у объекта ОДНА: ступени одного листа на
    другом были бы правдоподобны и неверны.
    """
    from ..ingestion import form_templates as ft

    return await (ft.get(conn, object_id, code) if code else ft.only(conn, object_id))


def _levels_of(tpl) -> Optional[Dict]:
    raw = tpl["levels"]
    return json.loads(raw) if isinstance(raw, str) else (raw or None)


async def get_state(conn, object_id, code: Optional[str] = None) -> Dict:
    """Предложение системы и то, что уже подтверждено человеком.

    🔴 Подтверждение хранится вместе с ОТПЕЧАТКОМ формы, при котором его дали.
    Если форма изменилась, отпечаток в шаблоне другой, и подтверждение
    помечается устаревшим: применить старую иерархию к новому бланку значило бы
    молча показать неверную лестницу — тот же довод, по которому не применяется
    и сама разметка.

    У объекта из нескольких форм (книга Минэкономразвития) ступени у каждой
    свои: без кода отвечаем списком форм — выбирает человек.
    """
    from ..ingestion import form_templates as ft

    forms = [{"dataset_code": t["dataset_code"], "sheet_name": t["sheet_name"]}
             for t in await ft.for_object(conn, object_id)]
    if code is None and len(forms) == 1:
        code = forms[0]["dataset_code"]
    if code is None and len(forms) > 1:
        return {"forms": forms, "dataset_code": None, "needs_form": True,
                "suggestion": None, "confirmed": None, "stale": False, "has_template": True}
    tpl = await _template(conn, object_id, code)
    saved = None
    stale = False
    if tpl is not None:
        saved = _levels_of(tpl)
        if saved:
            stale = saved.get("fingerprint") != tpl["fingerprint"]
    return {"forms": forms, "dataset_code": code, "needs_form": False,
            # Графы по коду отбираем, только когда форм несколько: справочник
            # граф общий на объект, а у единственной формы он и есть её состав
            # (у выпусков, перенесённых строками, графы не объявлены вовсе).
            "suggestion": await suggest(conn, object_id, code if len(forms) > 1 else None),
            "confirmed": saved or None, "stale": stale,
            "has_template": tpl is not None}


async def save(conn, object_id, payload: Dict, user_id, code: Optional[str] = None) -> Dict:
    """Записать подтверждённые ступени в шаблон формы.

    Требуем существующий шаблон: он появляется при первом выпуске, и до него
    подтверждать нечего — форма ещё не размечена.
    """
    from ..ingestion import form_templates as ft

    tpl = await _template(conn, object_id, code)
    if tpl is None:
        if code is None and len(await ft.codes_with_template(conn, object_id)) > 1:
            raise ValueError("В объекте несколько форм — укажите, для какой подтверждаются ступени.")
        raise ValueError("Форма ещё не размечена — сначала выпустите по ней данные, "
                         "потом подтвердите ступени.")

    stored = {**payload, "fingerprint": tpl["fingerprint"],
              "confirmed_by": str(user_id) if user_id else None,
              "confirmed_at": datetime.now(timezone.utc).isoformat()}
    await ft.set_levels(conn, object_id, tpl["dataset_code"], stored)
    return stored


async def load_confirmed(conn, object_id, code: Optional[str] = None) -> Optional[Dict]:
    """Подтверждённые ступени формы, если они есть и не устарели.

    Единственная точка, которой пользуются дашборды: устаревшее подтверждение
    отсюда не выходит вовсе — лучше отсутствие лестницы, чем неверная.
    """
    # 🔴 Читаем шаблон НАПРЯМУЮ, а не через `get_state`: тот заодно считает
    # предложение системы (`suggest` — разбор всех граф формы по всей истории
    # выпусков), которое здесь не нужно. На РЦО это стоило 1,8 с, и платила их
    # КАЖДАЯ открытая страница дашборда (замер 24.09.2026).
    tpl = await _template(conn, object_id, code)
    if tpl is None:
        return None
    saved = _levels_of(tpl)
    if not saved or saved.get("fingerprint") != tpl["fingerprint"]:
        return None
    return saved
