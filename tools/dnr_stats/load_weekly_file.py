"""Загрузка ОДНОГО еженедельного файла «ДНР_статистика_на_ДД.ММ.ГГГГ.xlsx» во
все 12 ведомств раздела «Статистика услуг ДНР» (multi-release модель дат).

Файл заказчика по каждому ведомству несёт ДВЕ отчётные даты одновременно
(«…с 01.01.2026 по <прошлая дата>» и «…по <текущая дата>» в каждом блоке
столбцов) — это устройство самой формы, не наша прихоть. Скрипт извлекает из
каждого листа-ведомства ОБЕ точки и заводит по НЕДОСТАЮЩЕЙ из них новый
`dataset_release` (код `<dept>_offices`, `reporting_period_start` = дата).
Идемпотентно ПО СОДЕРЖИМОМУ, а не по дате (правило то же, что у штатного
«выпуска по листам», 22.09.2026): если release с этой (code, period) уже есть,
скрипт сверяет отпечаток значений — совпал, выпуск остаётся нетронутым;
разошёлся, прежний выпуск замещается (обратимо: он остаётся со статусом
`superseded`). Простое «дата уже есть — пропускаем» здесь не годится: ведомство
присылает исправленный файл за ту же неделю, и пропуск терял бы исправление
молча. Повторный запуск на ТОМ ЖЕ файле по-прежнему ничего не задваивает,
поэтому один и тот же файл можно (и нужно) прогонять и как «текущий», и как
источник данных за предыдущую дату — типичный сценарий, когда следующий
недельный файл приходит раньше, чем успели прогнать этот скрипт для прошлого.

Структура листа (проверена программно на файлах 12.08 и 19.08.2026, едина
для всех 12 ведомств): строка 3 — шапка, блок из 9 столбцов на услугу
(приоритет / оказывается / принято-прошлое / принято-текущее / прирост /
выдано-прошлое / выдано-текущее / прирост / комментарии), первый блок
начинается с 4-го столбца; строки 6.. — отделения (row_label = столбец
«МФЦ (адрес...)», НЕ «Субъект» — субъект один на все строки); строка 5 —
ИТОГО, пропускается.

Использование (внутри контейнера api, где есть openpyxl+asyncpg):
    docker cp <файл.xlsx> dashbord_api:/tmp/dnr_week.xlsx
    docker cp backend/app/modules/dnr_stats/departments.py \
        dashbord_api:/app/app/modules/dnr_stats/departments.py  # если каталог менялся
    docker exec -i dashbord_api python3 - < tools/dnr_stats/load_weekly_file.py

Если в файле появилось НОВОЕ ведомство или изменилось число услуг у
существующего — сначала дополнить `DEPARTMENTS` в
`backend/app/modules/dnr_stats/departments.py` (услуги достаются построчно из
строки 2 листа, см. `_parse_sheet`), иначе сработает `assert` и скрипт
остановится, ничего не испортив.
"""
import asyncio
import os
import re
import sys
from datetime import date

import asyncpg

# 🔴 Путь к приложению проставляем ДО первого импорта из `app`, а не перед
# вторым. Раньше `sys.path.insert` стоял ниже, и скрипт работал только когда
# его подавали на stdin из рабочего каталога `/app` (тогда путь давал сам
# Python). Запуск файлом — `docker exec … python3 /tmp/load_weekly_file.py` —
# падал с «No module named 'app'». Найдено загрузкой на боевой 22.09.2026.
sys.path.insert(0, "/app")

# Отпечаток значений считает ОБЩИЙ код приложения: скрипт запускается внутри
# контейнера api, где `app` доступен. Своя копия правила «те же это данные или
# другие» разошлась бы со штатным выпуском при первой же правке.
from app.modules.ingestion import mapping  # noqa: E402

# --- Править перед каждым новым файлом ---
SOURCE_FILE = "/tmp/dnr_week.xlsx"
# ------------------------------------------

# 🔴 Объект РЕЗОЛВИТСЯ ПО ВЕДОМСТВУ, а не задан одной константой.
# До 21.09.2026 здесь стоял общий `OBJECT_ID` объекта-заглушки, из которого
# 27.08 раздали 12 отдельных объектов (по объекту на ведомство — иначе
# автораспознавание форм, работающее по ОДНОМУ шаблону на объект, не могло
# проверить 12 разных бланков). Сам объект при этом никуда не делся: он был
# переименован в «Статистика услуг — МВД». То есть константа продолжала
# указывать на существующий объект, скрипт отработал бы без единой ошибки —
# и привязал бы выпуски и справочники ВСЕХ ведомств к МВД, тихо развалив
# разделение. Инструмент остался от прежней архитектуры и не был обновлён
# вместе с ней.
async def _object_for(conn, dataset_code: str, dept_name: str) -> str:
    """Объект ведомства: сперва тот, что уже владеет этим кодом набора.

    Код набора уникален в организации (`mapping.assert_code_free`), поэтому
    владелец определяется однозначно и переживает любое переименование.
    Имя — только запасной путь для ведомства, которое грузится впервые.
    """
    obj = await conn.fetchval(
        "select object_id from dataset_releases where code=$1 and object_id is not null "
        "order by created_at desc limit 1", dataset_code)
    if obj:
        return str(obj)
    obj = await conn.fetchval(
        "select id from objects where name = $1", f"Статистика услуг — {dept_name}")
    if obj:
        return str(obj)
    raise SystemExit(
        f"не найден объект для ведомства «{dept_name}» (код {dataset_code}). "
        "Заведите его в разделе «Объекты» — грузить ведомство в чужой объект нельзя: "
        "его данные попадут в чужие дашборды.")

from app.modules.dnr_stats.departments import DEPARTMENTS, field  # noqa: E402

SHEET_BY_CODE = {
    "mvd": "МВД", "fns": "ФНС", "rosreestr": "Росреестр", "socfond": "Соц.фонд",
    "mincifry": "Минцифры", "zags": "ЗАГС", "minjust": "Минюст", "tfoms": "ТФОМС",
    "fssp": "ФССП", "rosim": "Росимущество", "kbki": "КБКИ", "minoborony": "Минобороны",
}

RU_DATE_RE = re.compile(r"по (\d{2})\.(\d{2})\.(\d{4})")
_WS_RE = re.compile(r"\s+")


def _clean_addr(text: str) -> str:
    """Схлопывает переносы строк/повторные пробелы — как `ingestion.analyze._clean`.
    Без этого один и тот же офис в разных листах то и дело оказывался бы под
    РАЗНЫМИ ключами (лишний пробел в конце ячейки одного из ведомств), и
    список отделений/«Обзор» считали бы больше офисов, чем есть на самом деле
    (реальный случай: 71 вместо 63 — найдено и исправлено 27.08.2026)."""
    return _WS_RE.sub(" ", text).strip()


def _short_city(label: str) -> str:
    for marker in ("г. ", "г."):
        i = label.find(marker)
        if i != -1:
            return label[i + len(marker):].split(",")[0].strip()
    return label[:20]


def _parse_sheet(ws):
    """-> (n_blocks, date_prev, date_cur, offices{addr: {city, blocks:[...]}})."""
    row3 = [ws.cell(3, c).value for c in range(1, ws.max_column + 1)]
    row2 = [ws.cell(2, c).value for c in range(1, ws.max_column + 1)]
    starts = [c + 1 for c, v in enumerate(row3) if v and "Приоритетная" in str(v)]
    names = [re.sub(r"^\d+\.\s*", "", str(v).strip()) for v in row2 if v and re.match(r"^\d+\.", str(v).strip())]
    assert len(starts) == len(names), f"block/name count mismatch: {len(starts)} vs {len(names)}"
    n_blocks = len(starts)

    m_prev = RU_DATE_RE.search(str(ws.cell(3, starts[0] + 2).value or ""))
    m_cur = RU_DATE_RE.search(str(ws.cell(3, starts[0] + 3).value or ""))
    date_prev = date(int(m_prev.group(3)), int(m_prev.group(2)), int(m_prev.group(1)))
    date_cur = date(int(m_cur.group(3)), int(m_cur.group(2)), int(m_cur.group(1)))

    offices = {}
    for r in range(6, ws.max_row + 1):
        raw_addr = ws.cell(r, 3).value
        if not raw_addr:
            continue
        addr = _clean_addr(str(raw_addr))
        blocks = []
        for start in starts:
            okaz = ws.cell(r, start + 1).value
            if hasattr(okaz, "date") and callable(getattr(okaz, "date", None)):
                okaz = okaz.date().isoformat()
            elif hasattr(okaz, "isoformat"):
                okaz = okaz.isoformat()
            elif okaz is not None:
                okaz = str(okaz)
            blocks.append({
                "prioritet": ws.cell(r, start).value,
                "okazyvaetsya": okaz,
                "prinyato_prev": ws.cell(r, start + 2).value,
                "prinyato_cur": ws.cell(r, start + 3).value,
                "vydano_prev": ws.cell(r, start + 5).value,
                "vydano_cur": ws.cell(r, start + 6).value,
                "kommentarii": ws.cell(r, start + 8).value,
            })
        offices[addr] = {"city": _short_city(addr), "blocks": blocks}
    return n_blocks, date_prev, date_cur, offices


async def _existing_release(conn, org_id, code, period):
    return await conn.fetchval(
        "select id from dataset_releases where organization_id=$1 and code=$2 "
        "and reporting_period_start=$3 and status <> 'superseded'", org_id, code, period)


async def _ensure_canonical_fields(conn, object_id, dept_code, n_blocks, admin_id):
    rows = []
    for i in range(1, n_blocks + 1):
        rows += [
            (field(dept_code, i, "prinyato"), f"Услуга {i}: Принято"),
            (field(dept_code, i, "vydano"), f"Услуга {i}: Выдано"),
            (field(dept_code, i, "prioritet"), f"Услуга {i}: Приоритетная услуга"),
            (field(dept_code, i, "okazyvaetsya"), f"Услуга {i}: Услуга оказывается"),
            (field(dept_code, i, "kommentarii"), f"Услуга {i}: Комментарии по офисам"),
        ]
    for code, name in rows:
        await conn.execute(
            "insert into canonical_fields(object_id, code, name, data_type, created_by) "
            "values($1::uuid,$2,$3,'text',$4) on conflict (object_id, code) do nothing",
            object_id, code, name, admin_id)
    await conn.execute(
        "insert into canonical_fields(object_id, code, name, data_type, created_by) "
        "values($1::uuid,'gorod','Город','text',$2) on conflict (object_id, code) do nothing",
        object_id, admin_id)


def _num(v):
    return float(v) if isinstance(v, (int, float)) else None


async def _build_release(conn, org_id, object_id, dept_code, dataset_code, name_suffix,
                          period, admin_id, offices, which):
    """which: 'prev' или 'cur' — какую из двух колонок файла брать за значения.

    Возвращает (сколько значений записано, что произошло словами).
    """
    numbers, texts = [], []
    for i, (addr, off) in enumerate(offices.items()):
        texts.append((i, addr, "gorod", off["city"]))
        for svc_i, blk in enumerate(off["blocks"], start=1):
            if (pn := _num(blk[f"prinyato_{which}"])) is not None:
                numbers.append((i, addr, field(dept_code, svc_i, "prinyato"), pn))
            if (vn := _num(blk[f"vydano_{which}"])) is not None:
                numbers.append((i, addr, field(dept_code, svc_i, "vydano"), vn))
            if blk["prioritet"] is not None:
                texts.append((i, addr, field(dept_code, svc_i, "prioritet"), str(blk["prioritet"])))
            if blk["okazyvaetsya"] is not None:
                texts.append((i, addr, field(dept_code, svc_i, "okazyvaetsya"), str(blk["okazyvaetsya"])))
            if blk["kommentarii"]:
                texts.append((i, addr, field(dept_code, svc_i, "kommentarii"), str(blk["kommentarii"])))

    # 🔴 Решение принимается по СОДЕРЖИМОМУ, а не по наличию даты. Отпечаток
    # считает общий код приложения (`mapping.values_digest`) — тот же, которым
    # сверяется штатный «выпуск по листам»: заведи здесь свой, и два загрузчика
    # однажды разошлись бы в том, что считать «тем же самым файлом».
    fresh = [(i, addr, code, None, val, None) for i, addr, code, val in numbers]
    fresh += [(i, addr, code, val, None, None) for i, addr, code, val in texts]
    digest = mapping.values_digest(fresh)

    existing = await _existing_release(conn, org_id, dataset_code, period)
    if existing is not None:
        if await mapping.released_values_digest(conn, existing) == digest:
            return 0, "не изменился — выпуск оставлен"
        # Замещаем ДО вставки нового: частичный unique-индекс активных выпусков
        # иначе не даст создать второй за ту же дату.
        await conn.execute("update dataset_releases set status='superseded' where id=$1", existing)

    rel = await conn.fetchval(
        "insert into dataset_releases(organization_id,code,name,status,reporting_period_start,"
        "created_by,object_id) values($1,$2,$3,'validated',$4,$5,$6::uuid) returning id",
        org_id, dataset_code, f"{name_suffix} — {period.isoformat()}", period, admin_id, object_id)

    if numbers:
        await conn.executemany(
            "insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,value_number) "
            "values($1,$2,$3,$4,$5)", [(rel, *r) for r in numbers])
    if texts:
        await conn.executemany(
            "insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,value_text) "
            "values($1,$2,$3,$4,$5)", [(rel, *r) for r in texts])
    return len(numbers) + len(texts), ("перевыпущен — данные изменились" if existing else "выпущен")


async def main():
    import openpyxl

    conn = await asyncpg.connect(
        host=os.environ["POSTGRES_HOST"], port=int(os.environ["POSTGRES_PORT"]),
        user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"],
        database=os.environ["POSTGRES_DB"])
    org_id = await conn.fetchval("select id from organizations order by created_at limit 1")
    admin_id = await conn.fetchval("select id from users where login='admin'")
    wb = openpyxl.load_workbook(SOURCE_FILE, data_only=True)

    for code, meta in DEPARTMENTS.items():
        sheet_name = SHEET_BY_CODE.get(code)
        if sheet_name is None or sheet_name not in wb.sheetnames:
            print(f"{code:12s} — лист не найден в файле, пропущено")
            continue
        n_blocks, date_prev, date_cur, offices = _parse_sheet(wb[sheet_name])
        assert n_blocks == len(meta["services"]), (
            f"{code}: в файле {n_blocks} услуг, в каталоге {len(meta['services'])} — "
            "обновите DEPARTMENTS в departments.py, прежде чем грузить дальше")

        object_id = await _object_for(conn, meta["dataset_code"], meta["name"])
        await _ensure_canonical_fields(conn, object_id, code, n_blocks, admin_id)
        n1, how1 = await _build_release(conn, org_id, object_id, code, meta["dataset_code"],
                                         meta["name"], date_prev, admin_id, offices, "prev")
        n2, how2 = await _build_release(conn, org_id, object_id, code, meta["dataset_code"],
                                         meta["name"], date_cur, admin_id, offices, "cur")
        # Судьбу КАЖДОЙ даты называем словами: «0 значений» не различает
        # «этот файл мы уже грузили» и «данные за эту дату исправлены».
        print(f"{code:12s} услуг={n_blocks:2d}  {date_prev} {how1} ({n1})  |  {date_cur} {how2} ({n2})")

    await conn.close()
    print("\nГотово. «не изменился» = данные за эту дату совпали с уже выпущенными; "
          "«перевыпущен» = файл принёс другие цифры, прежний выпуск снят с использования "
          "и возвращается кнопкой.")


asyncio.run(main())
