"""Справочник отделений МФЦ — сведения, которых в системе не было нигде.

Отделение до сих пор жило ТОЛЬКО строкой данных (`dataset_values.row_label`),
которая приходит из отчёта и через интерфейс не правится. Адрес, телефон и
режим работы взять было неоткуда — а именно они показываются на точке карты.

Три правила, на которых держится модуль:

1. **Ключ — ИМЯ отделения, а не внешний id.** В присланном шаблоне имена
   уникальны (62 строки), а `id` дублируется: у ТОСП стоит id головного МФЦ
   (9 пар). Импорт по внешнему id молча склеил бы ТОСП с его головным
   отделением и потерял половину точек.
2. **Закрытое отделение не удаляется, а помечается недействующим.** Цифры за
   прошлые периоды по нему остаются, и удаление оборвало бы историю.
3. **Точка проверяется на попадание в контур, но не запрещается.** Контур —
   справочная геометрия, на самой границе он может расходиться с реальностью;
   запрет заблокировал бы работу, а предупреждение показывает промах сразу.
"""
from __future__ import annotations

import csv
import io
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

from ..audit import service as audit

CONTOUR_PATH = Path(__file__).with_name("geo") / "dnr_contour.geojson"

# Дни недели: ключ в hours → как записан в шаблоне и как показывается человеку.
DAYS = (
    ("mon", "пн", "Понедельник"),
    ("tue", "вт", "Вторник"),
    ("wed", "ср", "Среда"),
    ("thu", "чт", "Четверг"),
    ("fri", "пт", "Пятница"),
    ("sat", "сб", "Суббота"),
    ("sun", "вс", "Воскресенье"),
)
DAY_KEYS = [d[0] for d in DAYS]

FIELDS = ("name", "address", "city", "phone", "phone2", "email", "website",
          "hours", "note", "lat", "lon", "row_label", "is_active", "source_id")

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
# Значение дня режется ДО следующего дня недели, а не по запятой: в шаблоне
# запятая местами пропущена («сб: 08:00 - 17:00     вс: выходной»), и разбор
# по запятой делал рабочую субботу выходным днём — молча и правдоподобно.
_HOURS_RE = re.compile(
    r"\b(пн|вт|ср|чт|пт|сб|вс)\b\s*:?\s*(.*?)(?=\s*,?\s*\b(?:пн|вт|ср|чт|пт|сб|вс)\b\s*:?|$)",
    re.IGNORECASE)
# «г. Донецк, ул. …» / «пгт Тельманово, …» / «с. Красная Поляна, …»
_CITY_RE = re.compile(r"^\s*(?:г\.|гор\.|пгт\.?|пос\.?|с\.|сел\.|ст\.)\s*([^,]+)", re.IGNORECASE)


class MapError(Exception):
    """Доменная ошибка справочника отделений."""


# --- Разбор того, что приходит из шаблона ---------------------------------

def norm_text(s: Optional[str]) -> Optional[str]:
    """Схлопывание пробелов и переносов. В шаблоне встречается «МФЦ  по городу
    Енакиево» с двойным пробелом — без нормализации это отдельное имя, и
    повторный импорт завёл бы дубль отделения."""
    if s is None:
        return None
    out = re.sub(r"\s+", " ", str(s)).strip()
    return out or None


def parse_coords(raw: Optional[str]) -> tuple[Optional[float], Optional[float]]:
    """«48.009964,37.808141» → (широта, долгота). Пусто или мусор → (None, None):
    отделение без координат заводится и живёт в справочнике, просто не рисуется
    на карте (в шаблоне такое есть — МФЦ №9 по городу Донецк)."""
    if not raw:
        return None, None
    parts = [p.strip().replace(",", ".") for p in re.split(r"[;\s]+|,(?=\s*-?\d)", raw.strip()) if p.strip()]
    if len(parts) < 2:
        parts = [p.strip() for p in raw.split(",") if p.strip()]
    try:
        lat, lon = float(parts[0]), float(parts[1])
    except (ValueError, IndexError):
        return None, None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None, None
    return lat, lon


def parse_hours(raw: Optional[str]) -> dict:
    """«пн: 08:00 - 17:00,  вт: выходной, вс» → режим по дням.

    День без значения — выходной, а не «неизвестно»: в шаблоне хвост строки
    обрывается («сб: выходной,     вс»), и трактовать обрыв как рабочий день
    значило бы напечатать на карте часы, которых никто не называл.
    """
    out: dict = {}
    if not raw:
        return out
    for day_ru, value in _HOURS_RE.findall(raw):
        key = next((k for k, ru, _ in DAYS if ru == day_ru.lower()), None)
        if key is None:
            continue
        v = norm_text(value) or ""
        m = re.match(r"^(\d{1,2}[:.]\d{2})\s*[-–—]\s*(\d{1,2}[:.]\d{2})$", v)
        out[key] = {"from": _t(m.group(1)), "to": _t(m.group(2))} if m else None
    return out


def _t(s: str) -> str:
    h, m = re.split(r"[:.]", s)
    return f"{int(h):02d}:{m}"


def validate_hours(hours) -> dict:
    """Режим, пришедший из формы. Пускаем только «чч:мм» — иначе на карту
    уедет строка, которую нечем показать по дням."""
    if hours is None:
        return {}
    if not isinstance(hours, dict):
        raise MapError("Режим работы должен быть объектом по дням недели")
    out: dict = {}
    for key, v in hours.items():
        if key not in DAY_KEYS:
            raise MapError(f"Неизвестный день недели: {key}")
        if v in (None, "", {}):
            out[key] = None
            continue
        if not isinstance(v, dict) or "from" not in v or "to" not in v:
            raise MapError(f"{key}: ожидается «с» и «по» либо выходной")
        a, b = str(v["from"]).strip(), str(v["to"]).strip()
        if not _TIME_RE.match(a) or not _TIME_RE.match(b):
            raise MapError(f"{key}: время в формате чч:мм (например 08:00)")
        out[key] = {"from": a, "to": b}
    return out


def city_from_address(address: Optional[str]) -> Optional[str]:
    """Населённый пункт из адреса — для поиска и группировки списка. Города в
    отчёте отдельной графой нет, а листать шесть десятков адресов подряд
    неудобно."""
    if not address:
        return None
    m = _CITY_RE.match(address)
    return norm_text(m.group(1)) if m else None


# --- Контур республики ----------------------------------------------------

@lru_cache(maxsize=1)
def contour() -> dict:
    """Контур ДНР (WGS-84, 872 точки). Свойства исходника срезаны, имя своё.
    Лежит в бэкенде, а не в статике фронта, чтобы и проверка координат, и сама
    карта брали ОДНУ геометрию."""
    return json.loads(CONTOUR_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _rings() -> list:
    g = contour()["geometry"]
    return [g["coordinates"][0]] if g["type"] == "Polygon" else [p[0] for p in g["coordinates"]]


def point_inside(lat: Optional[float], lon: Optional[float]) -> Optional[bool]:
    """Попадает ли точка в контур (луч вправо, чётность пересечений).
    None — координат нет, судить не о чем."""
    if lat is None or lon is None:
        return None
    for ring in _rings():
        inside = False
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i][0], ring[i][1]
            x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
            if (y1 > lat) != (y2 > lat):
                x_at = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
                if lon < x_at:
                    inside = not inside
        if inside:
            return True
    return False


# --- Чтение справочника ---------------------------------------------------

def _out(r) -> dict:
    d = dict(r)
    d["id"] = str(d["id"])
    if isinstance(d.get("hours"), str):
        d["hours"] = json.loads(d["hours"])
    d["inside_contour"] = point_inside(d.get("lat"), d.get("lon"))
    return d


async def list_offices(conn, org_id, q: Optional[str] = None, only_active: bool = False) -> list:
    where = ["organization_id=$1"]
    args: list = [org_id]
    if only_active:
        where.append("is_active")
    if q:
        args.append(f"%{q.strip()}%")
        where.append(f"(name ilike ${len(args)} or address ilike ${len(args)} or city ilike ${len(args)})")
    rows = await conn.fetch(
        "select id, name, address, city, phone, phone2, email, website, hours, note, lat, lon, "
        "row_label, is_active, source_id, created_at, updated_at "
        f"from mfc_offices where {' and '.join(where)} "
        "order by is_active desc, city nulls last, name", *args)
    return [_out(r) for r in rows]


async def get_office(conn, org_id, office_id: str) -> dict:
    r = await conn.fetchrow(
        "select id, name, address, city, phone, phone2, email, website, hours, note, lat, lon, "
        "row_label, is_active, source_id, created_at, updated_at "
        "from mfc_offices where id=$1::uuid and organization_id=$2", office_id, org_id)
    if r is None:
        raise MapError("Отделение не найдено")
    return _out(r)


# --- Правка ---------------------------------------------------------------

def _clean(data: dict) -> dict:
    """Приведение полей формы к тому, что уедет в базу."""
    out = dict(data)
    for k in ("name", "address", "city", "phone", "phone2", "email", "website", "note", "row_label"):
        if k in out:
            out[k] = norm_text(out[k])
    if "hours" in out:
        out["hours"] = validate_hours(out["hours"])
    if out.get("name") is None and "name" in out:
        raise MapError("Название отделения обязательно")
    # Город не спрашиваем отдельно, если его можно прочитать из адреса: лишнее
    # поле в форме — лишний повод ошибиться.
    if not out.get("city") and out.get("address"):
        out["city"] = city_from_address(out["address"])
    for k in ("lat", "lon"):
        if k in out and out[k] is not None:
            out[k] = float(out[k])
    if (out.get("lat") is None) != (out.get("lon") is None) and ("lat" in out or "lon" in out):
        raise MapError("Координаты задаются парой: широта и долгота")
    return out


async def create_office(conn, org_id, user_id, data: dict) -> dict:
    d = _clean(data)
    if not d.get("name"):
        raise MapError("Название отделения обязательно")
    if await conn.fetchval("select 1 from mfc_offices where organization_id=$1 and name=$2", org_id, d["name"]):
        raise MapError(f"Отделение «{d['name']}» уже есть в справочнике")
    await _assert_row_free(conn, org_id, d.get("row_label"), None)
    r = await conn.fetchrow(
        "insert into mfc_offices(organization_id, name, address, city, phone, phone2, email, website, "
        "hours, note, lat, lon, row_label, is_active, source_id, created_by) "
        "values($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11,$12,$13,coalesce($14,true),$15,$16::uuid) "
        "returning id, name, address, city, phone, phone2, email, website, hours, note, lat, lon, "
        "row_label, is_active, source_id, created_at, updated_at",
        org_id, d["name"], d.get("address"), d.get("city"), d.get("phone"), d.get("phone2"),
        d.get("email"), d.get("website"), json.dumps(d.get("hours") or {}, ensure_ascii=False),
        d.get("note"), d.get("lat"), d.get("lon"), d.get("row_label"), d.get("is_active"),
        d.get("source_id"), str(user_id) if user_id else None)
    out = _out(r)
    await audit.write_event(conn, org_id, user_id, "create", "mfc_office", out["id"], new_data=out)
    return out


async def update_office(conn, org_id, user_id, office_id: str, patch: dict) -> dict:
    if not patch:
        raise MapError("Нечего менять")
    before = await get_office(conn, org_id, office_id)
    d = _clean(patch)
    # Режим работы СЛИВАЕТСЯ с сохранённым, а не заменяет его целиком: типовая
    # правка — один день («суббота стала выходной»), и замена набора стирала бы
    # остальные шесть дней молча. Любое состояние дня выразимо и при слиянии:
    # часы — объектом «с/по», выходной — null.
    if "hours" in d:
        d["hours"] = {**(before.get("hours") or {}), **d["hours"]}
    if "name" in d and d["name"] != before["name"] and await conn.fetchval(
            "select 1 from mfc_offices where organization_id=$1 and name=$2 and id<>$3::uuid",
            org_id, d["name"], office_id):
        raise MapError(f"Отделение «{d['name']}» уже есть в справочнике")
    if "row_label" in d:
        await _assert_row_free(conn, org_id, d["row_label"], office_id)
    cols = [k for k in d if k in FIELDS]
    if not cols:
        raise MapError("Нечего менять")
    sets, args = [], [office_id, org_id]
    for k in cols:
        args.append(json.dumps(d[k], ensure_ascii=False) if k == "hours" else d[k])
        sets.append(f"{k}=${len(args)}" + ("::jsonb" if k == "hours" else ""))
    r = await conn.fetchrow(
        f"update mfc_offices set {', '.join(sets)}, updated_at=now() "
        "where id=$1::uuid and organization_id=$2 "
        "returning id, name, address, city, phone, phone2, email, website, hours, note, lat, lon, "
        "row_label, is_active, source_id, created_at, updated_at", *args)
    if r is None:
        raise MapError("Отделение не найдено")
    out = _out(r)
    await audit.write_event(conn, org_id, user_id, "update", "mfc_office", office_id,
                            old_data=before, new_data=out)
    return out


async def delete_office(conn, org_id, user_id, office_id: str) -> None:
    before = await get_office(conn, org_id, office_id)
    await conn.execute("delete from mfc_offices where id=$1::uuid and organization_id=$2", office_id, org_id)
    await audit.write_event(conn, org_id, user_id, "delete", "mfc_office", office_id, old_data=before)


async def _assert_row_free(conn, org_id, row_label: Optional[str], self_id: Optional[str]) -> None:
    """Одна строка отчёта — одно отделение: иначе её нагрузка показалась бы
    дважды, в двух точках карты."""
    if not row_label:
        return
    owner = await conn.fetchrow(
        "select id, name from mfc_offices where organization_id=$1 and row_label=$2", org_id, row_label)
    if owner and (self_id is None or str(owner["id"]) != str(self_id)):
        raise MapError(f"Эта строка отчёта уже связана с отделением «{owner['name']}»")


# --- Импорт из шаблона ----------------------------------------------------

# Шаблон, по которому ведомство ведёт перечень отделений. Имена колонок
# принимаем в нескольких написаниях: файл выгружается разными системами.
CSV_ALIASES = {
    "name": ("name", "название", "наименование"),
    "address": ("adress", "address", "адрес"),
    "phone": ("telephone_1", "phone", "телефон"),
    "phone2": ("telephone_2", "phone2"),
    "email": ("mail", "email", "почта"),
    "website": ("website", "сайт"),
    "hours": ("operating_mode", "режим", "режим работы"),
    "note": ("information", "примечание"),
    "coords": ("coordinates", "координаты"),
    "source_id": ("id", "external_id"),
}


def _pick(row: dict, key: str) -> Optional[str]:
    for alias in CSV_ALIASES[key]:
        for k, v in row.items():
            if k and k.strip().lower().lstrip("﻿") == alias:
                return v
    return None


def parse_csv(raw: bytes) -> tuple[list, list]:
    """Разбор файла шаблона → (отделения, ошибки построчно).

    Разделитель определяется по самому файлу: ведомственная выгрузка идёт с
    точкой с запятой, а сохранённое из Excel — с запятой.
    """
    for enc in ("utf-8-sig", "cp1251"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise MapError("Не удалось прочитать файл: неизвестная кодировка")
    head = text.split("\n", 1)[0]
    delim = ";" if head.count(";") >= head.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    items, errors = [], []
    for i, row in enumerate(reader, start=2):
        name = norm_text(_pick(row, "name"))
        if not name:
            errors.append({"line": i, "error": "нет названия отделения"})
            continue
        lat, lon = parse_coords(_pick(row, "coords"))
        address = norm_text(_pick(row, "address"))
        items.append({
            "name": name,
            "address": address,
            "city": city_from_address(address),
            "phone": norm_text(_pick(row, "phone")),
            "phone2": norm_text(_pick(row, "phone2")),
            "email": norm_text(_pick(row, "email")),
            "website": norm_text(_pick(row, "website")),
            "hours": parse_hours(_pick(row, "hours")),
            "note": norm_text(_pick(row, "note")),
            "lat": lat, "lon": lon,
            "source_id": norm_text(_pick(row, "source_id")),
        })
    if not items and not errors:
        raise MapError("В файле нет ни одной строки с названием отделения")
    return items, errors


async def import_csv(conn, org_id, user_id, raw: bytes, update_existing: bool = False) -> dict:
    """Загрузка перечня отделений файлом.

    По умолчанию существующие отделения НЕ трогаются: повторный импорт того же
    файла иначе затёр бы правки, сделанные руками (поправленный телефон,
    уточнённые координаты), и человек об этом не узнал бы. Обновление
    существующих — отдельный осознанный выбор.
    """
    items, errors = parse_csv(raw)
    created = updated = skipped = 0
    outside = []
    for it in items:
        exists = await conn.fetchrow(
            "select id from mfc_offices where organization_id=$1 and name=$2", org_id, it["name"])
        try:
            if exists is None:
                await create_office(conn, org_id, user_id, dict(it))
                created += 1
            elif update_existing:
                await update_office(conn, org_id, user_id, str(exists["id"]), dict(it))
                updated += 1
            else:
                skipped += 1
                continue
        except MapError as e:
            errors.append({"line": None, "error": f"{it['name']}: {e}"})
            continue
        if it["lat"] is not None and point_inside(it["lat"], it["lon"]) is False:
            outside.append(it["name"])
    return {
        "total": len(items), "created": created, "updated": updated, "skipped": skipped,
        "no_coords": [i["name"] for i in items if i["lat"] is None],
        "outside_contour": outside,
        "errors": errors,
    }


# --- Сверка со строками отчёта -------------------------------------------

_TOK_RE = re.compile(r"[0-9a-zа-яё]+", re.IGNORECASE)
# «ТОСП» в стоп-словах НЕТ намеренно: это не шум, а единственное, что
# отличает обособленное подразделение от головного отделения.
_STOP = {"мфц", "гбу", "днр", "город", "городу", "пгт", "ул", "пр", "кт", "бул", "б",
         "пл", "проспект", "улица", "село", "поселок", "посёлок", "по", "с", "г",
         "отделение", "отделения"}


def _tokens(s: Optional[str]) -> set:
    if not s:
        return set()
    return {t for t in _TOK_RE.findall(s.lower()) if len(t) >= 2 and t not in _STOP}


def suggest_office(row_label: str, offices: list) -> Optional[dict]:
    """Какое отделение справочника похоже на строку отчёта.

    В отчёте адрес записан иначе, чем в справочнике («№ 3 ГБУ "МФЦ ДНР"
    Мариуполь, ул. Нахимова, 172» против «МФЦ №3 по городу Мариуполь» +
    «г. Мариуполь, ул. Нахимова, 172»), поэтому сравниваем НАБОРЫ СЛОВ имени и
    адреса, выбросив общие для всех («МФЦ», «ГБУ», «ДНР») — они не различают
    ничего. Система только предлагает: связывает человек.
    """
    a = _tokens(row_label)
    if not a:
        return None
    # 🔴 ТОСП сопоставляется только с ТОСП. В отчёте у обособленного
    # подразделения стоит адрес ГОЛОВНОГО отделения («ТОСП в с. Красная Поляна
    # … г. Волноваха, ул. Ленина, 88»), и по словам адреса оно перетягивается к
    # головному — а это чужая точка на карте и чужая нагрузка. Тип объекта
    # решает раньше похожести.
    a_tosp = "тосп" in a
    scored = []
    for o in offices:
        b = _tokens(o["name"]) | _tokens(o.get("address"))
        if not b or ("тосп" in _tokens(o["name"])) != a_tosp:
            continue
        common = len(a & b)
        scored.append((common / min(len(a), len(b)), common, o))
    if not scored:
        return None
    scored.sort(key=lambda x: (-x[0], -x[1]))
    best_score, best_common, best = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    # Три условия, и каждое закрывает свой способ ошибиться:
    #   доля совпадения — чтобы не предлагать случайное пересечение;
    #   ОДНОЗНАЧНОСТЬ — если так же похожи двое, подсказка сбивает с толку
    #     сильнее, чем её отсутствие: человек доверится первой попавшейся;
    #   два общих слова — для длинной строки; у строки из одного значимого
    #     слова требовать два невозможно, там хватает однозначности.
    if best_score < 0.5 or best_score <= second:
        return None
    if best_common < 2 and len(a) > 1:
        return None
    return {"id": best["id"], "name": best["name"], "score": round(best_score, 2)}


async def unmatched(conn, org_id, dataset_code: str) -> dict:
    """Строки последнего отчёта, которым не сопоставлено отделение.

    Это и есть «система сама заметила»: без такой сверки новое отделение
    попадает в цифры, но не на карту, и обнаружить это можно только случайно.
    """
    rel = await conn.fetchrow(
        "select id, reporting_period_start from dataset_releases "
        "where organization_id=$1 and code=$2 and status <> 'superseded' "
        "order by reporting_period_start desc nulls last, created_at desc limit 1",
        org_id, dataset_code)
    if rel is None:
        raise MapError(f"Набор данных «{dataset_code}» не найден")
    rows = [r["row_label"] for r in await conn.fetch(
        "select distinct row_label from dataset_values where dataset_release_id=$1 "
        "and row_label is not null and row_label <> '' order by row_label", rel["id"])]
    offices = await list_offices(conn, org_id)
    taken = {o["row_label"] for o in offices if o["row_label"]}
    free = [o for o in offices if not o["row_label"]]
    new_rows = [{"row_label": r, "suggestion": suggest_office(r, free)} for r in rows if r not in taken]
    return {
        "dataset_code": dataset_code,
        "period": rel["reporting_period_start"].isoformat() if rel["reporting_period_start"] else None,
        "rows_total": len(rows),
        "linked": len(rows) - len(new_rows),
        "unmatched": new_rows,
        "offices_without_row": [{"id": o["id"], "name": o["name"], "city": o["city"]} for o in free],
    }

async def link_suggested(conn, org_id, user_id, dataset_code: str, max_passes: int = 5) -> dict:
    """Связать разом все строки отчёта, в которых подсказка однозначна.

    Ручное связывание шести десятков отделений — это шесть десятков нажатий на
    одно и то же; при этом каждая связка обратима, а подсказка выдаётся только
    при однозначном совпадении. Поэтому массовая операция допустима — но с
    тремя ограничениями, и каждое существенно:

    1. **Подсказки считаются ЗДЕСЬ, а не приходят с экрана.** Иначе связка
       опиралась бы на то, что человек видел минуту назад, — а за это время
       отделение могли завести, переименовать или связать из другой вкладки.
    2. **Идём от самых уверенных к менее уверенным и занятое не перезаписываем.**
       Две строки отчёта могут указывать на одно отделение; молча связать
       последнюю значило бы отдать ей чужую нагрузку.
    3. **Повторяем проходы, пока связывается хоть что-то.** Подсказка молчит
       при неоднозначности, а неоднозначность спадает по мере того, как
       конкуренты разбираются: «Отделение № 3 … пр-т Ильича» и «ТОСП … № 9»
       находятся только вторым проходом, когда соседние номера уже заняты
       (проверено на настоящих данных). Без цикла второе нажатие той же кнопки
       давало бы иной результат, чем первое, — поведение, которое человек
       справедливо считает случайным.
    """
    linked: list[dict] = []
    conflicts: list[dict] = []
    for _ in range(max_passes):
        report = await unmatched(conn, org_id, dataset_code)
        pairs = [(u["suggestion"]["score"], u["row_label"], u["suggestion"])
                 for u in report["unmatched"] if u["suggestion"]]
        if not pairs:
            break
        pairs.sort(key=lambda x: -x[0])
        taken: set = set()
        before = len(linked)
        for _score, row_label, sug in pairs:
            if sug["id"] in taken:
                continue  # разберётся следующим проходом, когда станет виднее
            try:
                await update_office(conn, org_id, user_id, sug["id"], {"row_label": row_label})
            except MapError as e:
                conflicts.append({"row_label": row_label, "office": sug["name"], "reason": str(e)})
                continue
            taken.add(sug["id"])
            linked.append({"row_label": row_label, "office": sug["name"]})
        if len(linked) == before:
            break

    report = await unmatched(conn, org_id, dataset_code)
    return {
        "linked": len(linked),
        "items": linked,
        "conflicts": conflicts,
        # Что осталось человеку: без этого «связано 59 из 62» выглядит как
        # потеря трёх строк, хотя это расхождения в самих данных.
        "left_manual": [u["row_label"] for u in report["unmatched"]],
    }
