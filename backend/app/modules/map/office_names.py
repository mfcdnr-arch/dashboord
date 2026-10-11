"""Эталонные названия отделений: система запоминает, как разные формы пишут
одно и то же отделение, и при выпуске сама подменяет вариант эталоном.

Эталон — строка отчёта, связанная с отделением в справочнике
(`mfc_offices.row_label`): ею пользуются ежедневный отчёт и «окна», по ней
отделение стоит на карте. Остальные формы пишут то же отделение иначе —
«Отделение МФЦ № 3 г. Донецк», «Отделение №3 ГБУ «МФЦ ДНР» г. Донецк, пр-кт
Ильича, 63а», — и для системы это разные строки: формы не сопоставляются, а на
карту ничего из них не попадает.

Четыре правила, и каждое закрывает свой способ ошибиться:

1. **Незнакомое название молча НЕ подменяется.** Система предлагает отделение
   (по номеру, населённому пункту и типу), подтверждает человек — один раз.
   Правдоподобная подмена не тем отделением увела бы цифры в чужую строку, и
   заметить это потом почти невозможно.
2. **ТОСП ≠ головное отделение.** У обособленного подразделения в строке стоит
   адрес головного, и по похожести оно перетягивается к нему (урок карты,
   12.09). Тип объекта решает раньше любой похожести.
3. **Подсказка только однозначная.** Нет номера в названии («ТОСП г. Донецк,
   пр-кт Дзержинского, 13») — подходят три ТОСП Донецка, и подсказки нет:
   угаданная наугад хуже отсутствующей.
4. **Подмена не склеивает строки.** Если в том же выпуске уже есть строка с
   эталонным названием, вариант НЕ переименовывается — иначе одно отделение
   встало бы дважды и его цифры сложились бы. Такой выпуск называется.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from ... import cache
from ..audit import service as audit
from ..notifications import service as notif

# Населённый пункт — первое слово после пометки «г.», «пгт», «с.», «пос.» или
# слов «по городу». Пометка не должна быть частью слова («пгт» содержит «г»,
# «городу» начинается с «г»), а после неё — точка, запятая или пробел: «г.Донецк»
# и «г, Донецк» встречаются в настоящих отчётах.
_LOC_RE = re.compile(
    r"(?<![а-я])(?:по\s+городу|пгт|пос|г|с)(?:\s*[.,]\s*|\s+)([а-я]{3,})")
_NUM_RE = re.compile(r"№\s*(\d+)")

# Сколько названий формы должно быть отделениями (эталоны, известные варианты
# или уверенные подсказки), чтобы форма считалась «формой по отделениям».
# Иначе незнакомыми «отделениями» объявлялись бы строки реестра вопросов.
OFFICE_FORM_SHARE = 0.5
OFFICE_FORM_MIN_ROWS = 3


def label_key(s: Optional[str]) -> str:
    """Ключ варианта: регистр, «ё» и лишние пробелы не делают название другим."""
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip().lower().replace("ё", "е")


def parse_label(s: Optional[str]) -> Optional[dict]:
    """«ТОСП в пгт Ялта Отделения МФЦ пгт Мангуш» → тип, номер, населённые пункты.

    None — в названии нет ни одного населённого пункта, судить не о чем
    (точка, «Итого», «Отделение ГБУ «МФЦ ДНР» Докучаевск» без пометки «г.»).
    """
    low = label_key(s).replace("-", " ")
    locs = _LOC_RE.findall(low)
    if not locs:
        return None
    m = _NUM_RE.search(low)
    return {"tosp": "тосп" in low, "num": int(m.group(1)) if m else None, "locs": locs}


def _fits(label: dict, office: dict) -> bool:
    """Подходит ли разобранное название к разобранному названию отделения.

    Номер в названии строки обязан совпасть; нет номера — подходит любой (и
    тогда спасает только однозначность). Головное отделение сравнивается по
    первому населённому пункту, ТОСП — по стольким, сколько названо с обеих
    сторон: «ТОСП в пгт Андреевка … пгт Тельманово» отличает Андреевку от Ялты.
    """
    if label["tosp"] != office["tosp"]:
        return False
    if label["num"] is not None and label["num"] != office["num"]:
        return False
    if label["num"] is None and office["num"] is not None and not label["tosp"]:
        # «Отделение МФЦ г. Донецк» без номера к «№ 7 г. Донецк» не подходит:
        # у головного отделения номер — часть имени, а не уточнение.
        return False
    n = 1 if not label["tosp"] else min(len(label["locs"]), len(office["locs"]), 2)
    return label["locs"][:n] == office["locs"][:n]


def office_keys(office: dict) -> list:
    """Разборы отделения — по имени в справочнике и по его эталонной строке.
    Имя надёжнее («ТОСП г. Донецк МФЦ №3 г. Донецк» говорит, чьё это ТОСП), а
    эталонная строка нужна там, где имя записано иначе."""
    out = []
    for s in (office.get("name"), office.get("row_label")):
        p = parse_label(s)
        if p:
            out.append(p)
    return out


def suggest(label: str, offices: list) -> Optional[dict]:
    """Единственное отделение, к которому подходит название, — или None."""
    p = parse_label(label)
    if p is None:
        return None
    hits = [o for o in offices if any(_fits(p, k) for k in o["_keys"])]
    if len(hits) != 1:
        return None
    o = hits[0]
    why = ["ТОСП" if p["tosp"] else "головное отделение"]
    if p["num"] is not None:
        why.append(f"№ {p['num']}")
    why.append(", ".join(x.capitalize() for x in p["locs"][:2]))
    return {"office_id": str(o["id"]), "office": o["name"], "target": o["row_label"],
            "reason": "совпали " + " · ".join(why)}


# --- Подмена при выпуске ----------------------------------------------------

async def load_alias_map(conn, org_id) -> dict:
    """{ключ варианта → эталонная строка}: только подтверждённые соответствия
    отделениям, у которых эталон есть."""
    rows = await conn.fetch(
        "select a.label_key, o.row_label from office_name_aliases a "
        "join mfc_offices o on o.id = a.office_id "
        "where a.organization_id=$1 and a.status='confirmed' and o.row_label is not null",
        org_id)
    return {r["label_key"]: r["row_label"] for r in rows if label_key(r["row_label"]) != r["label_key"]}


def rename_map(labels: Iterable[str], aliases: Optional[dict]) -> dict:
    """{вариант → эталон} для набора названий одного выпуска.

    Вариант, у которого в том же наборе уже есть эталонный близнец, остаётся
    как есть, и два разных варианта одного отделения — тоже: переименование
    склеило бы две строки в одно отделение, и его цифры сложились бы.
    """
    if not aliases:
        return {}
    present = set(labels)
    claim: dict = {}
    for lab in present:
        canon = aliases.get(label_key(lab))
        if canon and canon != lab:
            claim.setdefault(canon, set()).add(lab)
    return {next(iter(labs)): canon for canon, labs in claim.items()
            if len(labs) == 1 and canon not in present}


def canonicalize(values: list, aliases: Optional[dict]) -> list:
    """Кортежи выпуска (row_index, row_label, …) с эталонными названиями."""
    if not aliases or not values:
        return values
    rename = rename_map((v[1] for v in values), aliases)
    if not rename:
        return values
    return [(v[0], rename[v[1]], *v[2:]) if v[1] in rename else v for v in values]


# --- Обзор: какие названия система не узнала --------------------------------

async def _offices(conn, org_id) -> list:
    rows = await conn.fetch(
        "select id, name, row_label, is_active from mfc_offices where organization_id=$1 "
        "order by name", org_id)
    out = []
    for r in rows:
        d = dict(r)
        d["_keys"] = office_keys(d)
        out.append(d)
    return out


async def _decisions(conn, org_id) -> dict:
    rows = await conn.fetch(
        "select a.id, a.label, a.label_key, a.status, a.office_id, o.name as office, "
        "o.row_label as target, a.decided_at, a.seen_code "
        "from office_name_aliases a left join mfc_offices o on o.id = a.office_id "
        "where a.organization_id=$1", org_id)
    return {r["label_key"]: dict(r) for r in rows}


def _classify(labels: Iterable[str], offices: list, decided: dict) -> dict:
    """Разбор названий одной формы: эталоны, известные, незнакомые."""
    canon = {label_key(o["row_label"]) for o in offices if o["row_label"]}
    known, unknown, ignored = 0, [], 0
    suggestible = 0
    for lab in labels:
        k = label_key(lab)
        if not k:
            continue
        if k in canon:
            known += 1
            continue
        d = decided.get(k)
        if d and d["status"] == "confirmed":
            known += 1  # вариант подтверждён, но в старом выпуске остался (склейка)
            continue
        if d and d["status"] == "ignored":
            ignored += 1
            continue
        sug = suggest(lab, offices)
        if sug:
            suggestible += 1
        unknown.append({"label": lab, "suggestion": sug})
    total = known + len(unknown)
    office_form = total >= OFFICE_FORM_MIN_ROWS and (known + suggestible) / total >= OFFICE_FORM_SHARE
    return {"known": known, "unknown": unknown, "ignored": ignored,
            "total": total, "office_form": office_form}


async def review(conn, org_id) -> dict:
    """Что система не узнала во ВСЕХ формах по отделениям.

    Читаются названия всех действующих выпусков (одним запросом: на стенде с
    4,8 млн значений — около двух секунд), поэтому обзор открывают кнопкой, а
    не при каждом заходе на карту. Уведомление о незнакомых названиях после
    выпуска смотрит только сам выпуск и стоит копейки.
    """
    offices = await _offices(conn, org_id)
    decided = await _decisions(conn, org_id)
    rows = await conn.fetch(
        "select dr.code, min(o.name) as object_name, dv.row_label "
        "from dataset_releases dr join dataset_values dv on dv.dataset_release_id = dr.id "
        "left join objects o on o.id = dr.object_id "
        "where dr.organization_id=$1 and dr.status <> 'superseded' "
        "and dv.row_label is not null and dv.row_label <> '' "
        "group by dr.code, dv.row_label", org_id)
    by_code: dict = {}
    names: dict = {}
    for r in rows:
        by_code.setdefault(r["code"], []).append(r["row_label"])
        names.setdefault(r["code"], r["object_name"])
    forms = []
    items: dict = {}
    for code, labels in by_code.items():
        c = _classify(labels, offices, decided)
        if not c["office_form"]:
            continue
        forms.append({"code": code, "object_name": names.get(code), "total": c["total"],
                      "known": c["known"], "unknown": len(c["unknown"]), "ignored": c["ignored"]})
        for u in c["unknown"]:
            it = items.setdefault(label_key(u["label"]), {
                "label": u["label"], "suggestion": u["suggestion"], "forms": []})
            it["forms"].append(code)
    # Формы, где больше всего эталонов, — первыми: их варианты надёжнее всего
    # становятся эталоном у ещё не связанного отделения.
    forms.sort(key=lambda f: (-(f["known"] / f["total"]), f["code"]))
    rank = {f["code"]: i for i, f in enumerate(forms)}
    out_items = sorted(items.values(), key=lambda i: (
        i["suggestion"] is None, min(rank[c] for c in i["forms"]), i["label"]))
    return {
        "forms": forms,
        "items": out_items,
        "with_suggestion": sum(1 for i in out_items if i["suggestion"]),
        "decisions": [
            {"id": str(d["id"]), "label": d["label"], "status": d["status"],
             "office": d["office"], "target": d["target"], "decided_at": d["decided_at"]}
            for d in sorted(decided.values(), key=lambda d: d["label"])
            if d["status"] in ("confirmed", "ignored")],
        "offices": [{"id": str(o["id"]), "name": o["name"], "row_label": o["row_label"]}
                    for o in offices if o["is_active"]],
    }


# --- Решение человека --------------------------------------------------------

async def _rename_values(conn, org_id, pairs: list) -> dict:
    """Переименовать варианты в эталоны во всех выпусках организации — ОДНИМ
    проходом по таблице значений: по проходу на вариант было бы по секунде на
    каждое из сотни названий.

    Выпуск пропускается для пары «вариант → эталон», если в нём эталон уже
    есть или в нём же встречаются два варианта одного эталона: переименование
    склеило бы две строки в одно отделение. Такие выпуски возвращаются списком.
    """
    if not pairs:
        return {"values": 0, "releases": 0, "conflicts": []}
    labels = [p[0] for p in pairs]
    canons = [p[1] for p in pairs]
    await conn.execute(
        "create temp table if not exists _office_rename "
        "(rid uuid, label text, canon text, blocked boolean) on commit drop")
    await conn.execute("truncate _office_rename")
    # Где встречаются варианты: (выпуск, вариант, эталон) + признак склейки.
    # Оба признака считаются хэш-соединениями за один проход, без вложенных
    # подзапросов по строкам: на сотне вариантов вложенный подсчёт был квадратичным.
    await conn.execute(
        "with m(label, canon) as (select * from unnest($2::text[], $3::text[])), "
        "hit as (select distinct dv.dataset_release_id as rid, m.label, m.canon "
        "  from dataset_values dv join m on dv.row_label = m.label "
        "  join dataset_releases dr on dr.id = dv.dataset_release_id and dr.organization_id=$1), "
        "has_canon as (select distinct dv.dataset_release_id as rid, dv.row_label as canon "
        "  from dataset_values dv where dv.dataset_release_id in (select rid from hit) "
        "  and dv.row_label in (select canon from m)) "
        "insert into _office_rename "
        "select h.rid, h.label, h.canon, "
        "  count(*) over (partition by h.rid, h.canon) > 1 or hc.rid is not null "
        "from hit h left join has_canon hc on hc.rid = h.rid and hc.canon = h.canon",
        org_id, labels, canons)
    res = await conn.fetchrow(
        "with upd as (update dataset_values dv set row_label = r.canon from _office_rename r "
        "where not r.blocked and dv.dataset_release_id = r.rid and dv.row_label = r.label "
        "returning dv.dataset_release_id) "
        "select count(*) as n, count(distinct dataset_release_id) as r from upd")
    conflicts = await conn.fetch(
        "select dr.code, dr.reporting_period_start as period, r.label from _office_rename r "
        "join dataset_releases dr on dr.id = r.rid where r.blocked order by 1, 2")
    # Права на строки записаны названием строки — переезжают вместе с ним,
    # иначе отделу, которому была открыта «его» строка, она молча закрылась бы.
    await conn.execute(
        "with m(label, canon) as (select * from unnest($2::text[], $3::text[])) "
        "update data_row_acl a set row_label = m.canon from m, objects o "
        "where a.row_label = m.label and o.id = a.object_id and o.organization_id=$1 "
        "and not exists (select 1 from data_row_acl b where b.object_id=a.object_id "
        "and b.department_id=a.department_id and b.row_label=m.canon)", org_id, labels, canons)
    return {"values": res["n"], "releases": res["r"],
            "conflicts": [{"code": c["code"], "label": c["label"],
                           "period": c["period"].isoformat() if c["period"] else None}
                          for c in conflicts]}


async def _upsert(conn, org_id, user_id, label: str, status: str, office_id: Optional[str]) -> str:
    return str(await conn.fetchval(
        "insert into office_name_aliases(organization_id, label, label_key, status, office_id, "
        "decided_by, decided_at) values($1,$2,$3,$4,$5::uuid,$6::uuid,now()) "
        "on conflict (organization_id, label_key) do update set label=excluded.label, "
        "status=excluded.status, office_id=excluded.office_id, decided_by=excluded.decided_by, "
        "decided_at=now() returning id",
        org_id, label, label_key(label), status, office_id, str(user_id) if user_id else None))


async def confirm(conn, org_id, user_id, items: list) -> dict:
    """Решения человека по списку названий: [{label, office_id | None}].

    office_id = None — «это не отделение», больше не спрашивать.
    У отделения ещё нет эталона — вариант им и становится (так устроено и
    ручное связывание на карте); есть — вариант запоминается и уже выпущенные
    данные переименовываются.
    """
    from .service import MapError, update_office

    offices = {str(o["id"]): o for o in await _offices(conn, org_id)}
    linked, aliased, ignored, errors = [], [], [], []
    pairs: list = []
    for it in items:
        label = (it.get("label") or "").strip()
        if not label:
            continue
        oid = it.get("office_id")
        if not oid:
            aid = await _upsert(conn, org_id, user_id, label, "ignored", None)
            ignored.append(label)
            await audit.write_event(conn, org_id, user_id, "update", "office_alias", aid,
                                    new_data={"label": label, "status": "ignored"})
            continue
        o = offices.get(str(oid))
        if o is None:
            errors.append({"label": label, "error": "отделение не найдено"})
            continue
        if not o["row_label"]:
            try:
                await update_office(conn, org_id, user_id, str(oid), {"row_label": label})
            except MapError as e:
                errors.append({"label": label, "error": str(e)})
                continue
            o["row_label"] = label
            linked.append({"label": label, "office": o["name"]})
            continue
        if label_key(o["row_label"]) == label_key(label):
            continue
        aid = await _upsert(conn, org_id, user_id, label, "confirmed", str(oid))
        await audit.write_event(conn, org_id, user_id, "update", "office_alias", aid,
                                new_data={"label": label, "office": o["name"], "target": o["row_label"]})
        pairs.append((label, o["row_label"]))
        aliased.append({"label": label, "office": o["name"], "target": o["row_label"]})
    renamed = await _rename_values(conn, org_id, pairs)
    if renamed["values"] or linked:
        await cache.delete_prefix("wd:")
    return {"linked": linked, "aliased": aliased, "ignored": ignored, "errors": errors,
            "renamed_values": renamed["values"], "renamed_releases": renamed["releases"],
            "conflicts": renamed["conflicts"]}


async def confirm_suggested(conn, org_id, user_id, max_passes: int = 5) -> dict:
    """Подтвердить разом все однозначные подсказки.

    Проходы повторяются, как у массового связывания на карте: когда одно
    отделение получает эталон, варианты его соседей перестают быть
    неоднозначными. Одно отделение за проход получает не больше одного
    варианта-эталона — иначе эталоном стал бы случайный из них.
    """
    total = {"linked": [], "aliased": [], "ignored": [], "errors": [],
             "renamed_values": 0, "renamed_releases": 0, "conflicts": []}
    for _ in range(max_passes):
        rev = await review(conn, org_id)
        offices = {o["id"]: o for o in rev["offices"]}
        batch, fresh_target = [], set()
        for it in rev["items"]:
            s = it["suggestion"]
            if not s:
                continue
            if not offices.get(s["office_id"], {}).get("row_label"):
                if s["office_id"] in fresh_target:
                    continue  # эталон выберется этим проходом, вариант — следующим
                fresh_target.add(s["office_id"])
            batch.append({"label": it["label"], "office_id": s["office_id"]})
        if not batch:
            break
        res = await confirm(conn, org_id, user_id, batch)
        for k in ("linked", "aliased", "ignored", "errors", "conflicts"):
            total[k] += res[k]
        total["renamed_values"] += res["renamed_values"]
        total["renamed_releases"] += res["renamed_releases"]
        if not res["linked"] and not res["aliased"]:
            break
    rev = await review(conn, org_id)
    total["left_manual"] = [i["label"] for i in rev["items"]]
    return total


async def forget(conn, org_id, user_id, alias_id: str) -> None:
    """Забыть решение. Уже переименованные данные остаются как есть: обратно их
    не отличить от строк, которые с эталоном пришли изначально."""
    row = await conn.fetchrow(
        "delete from office_name_aliases where id=$1::uuid and organization_id=$2 "
        "returning label, status", alias_id, org_id)
    if row is None:
        from .service import MapError
        raise MapError("Соответствие не найдено")
    await audit.write_event(conn, org_id, user_id, "delete", "office_alias", alias_id,
                            old_data={"label": row["label"], "status": row["status"]})


# --- После выпуска ----------------------------------------------------------

async def after_release(conn, org_id, code: str, release_id, object_id=None) -> Optional[dict]:
    """Незнакомые названия отделений в только что выпущенном отчёте → одно
    уведомление управляющим, по каждому названию — один раз.

    Смотрит только этот выпуск, поэтому дёшево. Не форма по отделениям
    (реестр, сводка) — молчит.
    """
    labels = [r["row_label"] for r in await conn.fetch(
        "select distinct row_label from dataset_values where dataset_release_id=$1 "
        "and row_label is not null and row_label <> ''", release_id)]
    if not labels:
        return None
    offices = await _offices(conn, org_id)
    if not offices:
        return None
    decided = await _decisions(conn, org_id)
    c = _classify(labels, offices, decided)
    if not c["office_form"] or not c["unknown"]:
        return None
    fresh = [u for u in c["unknown"] if label_key(u["label"]) not in decided]
    if not fresh:
        return None
    for u in fresh:
        await conn.execute(
            "insert into office_name_aliases(organization_id, label, label_key, status, "
            "suggested_office_id, seen_code, notified_at) values($1,$2,$3,'pending',$4::uuid,$5,now()) "
            "on conflict (organization_id, label_key) do nothing",
            org_id, u["label"], label_key(u["label"]),
            u["suggestion"]["office_id"] if u["suggestion"] else None, code)
    users = await notif.management_user_ids(conn, org_id)
    payload = {"code": code, "count": len(fresh),
               "with_suggestion": sum(1 for u in fresh if u["suggestion"]),
               "examples": [u["label"] for u in fresh[:3]]}
    if object_id:
        await notif.notify(conn, org_id, "data.office_names", "object", str(object_id), payload, users)
    return payload
