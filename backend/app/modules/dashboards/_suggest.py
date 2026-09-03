"""Предложения виджетов и авто-сборка дашборда (вынесено из service.py).

Правила, не ИИ: по числовым полям датасета собираются готовые спецификации
виджетов; уже построенное для этого датасета из предложений вычитается.
Функции реэкспортируются из service.py — внешние вызовы не меняются.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import List, Optional

from ..metrics import resolver as mr
from ..metrics.data_suggestions import _clean, _is_main_slice, _split_name, _subject_key
from ._aggregate import is_share
from ._alerts import _cfg
from ._base import DashboardError

# Потолок карточек в авто-сборке на один датасет. Показываем ВСЕ показатели
# формы (у госформ их бывает полтора десятка), но у файла на сотню граф
# столько виджетов сделали бы страницу нечитаемой, а её открытие — медленным:
# каждая карточка считается отдельно. Остальные графы видны в таблице ниже.
MAX_AUTO_KPI = 24
# Потолок графиков динамики. Тренд — самое ценное, когда форм много, но каждый
# график считается отдельным запросом: на широкой форме страница открывалась бы
# заметно дольше. Остальные показатели добавляются кнопкой «💡 Предложить ещё».
MAX_AUTO_DYNAMICS = 16

# Пороги «нормы» для процента выполнения плана. Норма здесь не выдумана: 100 %
# — это сам план, а ниже 90 % отставание уже не наверстать незаметно. Первое
# сработавшее правило определяет цвет, поэтому danger стоит раньше warn.
PLAN_PCT_ALERTS = [
    {"level": "danger", "op": "lt", "value": 90, "label": "ниже 90 % плана"},
    {"level": "warn", "op": "lt", "value": 100, "label": "план не выполнен"},
    {"level": "good", "op": "gte", "value": 100, "label": "план выполнен"},
]


def _is_percent(unit) -> bool:
    return bool(unit) and "%" in str(unit)


def apply_default_alerts(widget_type: str, cfg: dict) -> dict:
    """Пороги по умолчанию там, где норма ИЗВЕСТНА, а не выдумана.

    Светофор без порогов красит все плитки одинаково серым — то есть выглядит
    сломанным ровно в том, ради чего его и берут. При этом норму выдумывать
    нельзя: у «доли доставленных» её нет. Но если у светофора задано поле
    ПЛАНА, норма известна — 100 % это сам план, тот же довод, по которому
    пороги получают полоса «план-факт» и спидометр выполнения.

    Ставим ТОЛЬКО когда ключа `alerts` нет вовсе. Пустой список — это осознанно
    снятые правила (человек убрал их в окне ⚠), и возвращать их значило бы
    спорить с ним при каждом сохранении.
    """
    has_plan = bool(cfg.get("plan_field")) or bool(cfg.get("pairs"))
    if widget_type in ("status_grid", "bullet", "thermometer") and has_plan and "alerts" not in cfg:
        cfg = dict(cfg)
        cfg["alerts"] = [dict(r) for r in PLAN_PCT_ALERTS]
    return cfg


def metric_widget_spec(unit, *, plan_execution: bool) -> tuple:
    """Каким виджетом показать расчётный показатель и с какими порогами.

    Процент — доля от известного целого, и на шкале он читается сразу: видно,
    близко ли к 100 %, а не только само число. Поэтому процентные показатели
    получают спидометр, остальные — карточку.

    Пороги ставим ТОЛЬКО проценту ВЫПОЛНЕНИЯ ПЛАНА: у него норма известна (сам
    план). У «доли доставленных» нормы нет — раскрасить её красным значило бы
    выдать выдумку за правило. Заданные пороги видны и правятся кнопкой ⚠.
    """
    cfg: dict = {}
    if plan_execution:
        cfg["alerts"] = [dict(r) for r in PLAN_PCT_ALERTS]
    return ("gauge" if _is_percent(unit) else "kpi"), cfg


# Размер виджета по типу — тот же, что выбирает авто-сборка. Собран в одном
# месте, чтобы «подгонка размеров» существующего дашборда и сборка нового не
# разошлись: иначе пересобранная страница выглядела бы иначе, чем подогнанная.
# Числа не из головы, а из замеров: на трёх колонках имя госформы обрезается до
# «Колич обращ за…», а карточка в три ряда не вмещает число вместе с шапкой.
WIDGET_SIZE = {
    # Высота 5 проверена ЗАМЕРОМ уже вместе с приростом и мини-графиком: на
    # 16 карточках при ширине окна 1100 и 1440 ни одна не включает прокрутку.
    # (Первый замер показал «перебор 16px» у семи карточек — это оказался
    # заголовок, намеренно обрезанный по трём строкам через line-clamp, а не
    # прокрутка содержимого. Мерить надо элементы с overflow auto/scroll.)
    "kpi": (4, 5),
    # Группа разрезов: высота считается по числу строк при сборке (см. ниже).
    "kpi_group": (4, 8),
    "gauge": (4, 7),
    "plan_fact": (6, 6),
    # Высота 7, а не 6: ЗАМЕР показал, что в шести рядах виджет стоит впритык —
    # график уже прижат к своему минимуму (118px), а под двумя строками итогов
    # («к пред. периоду» и «за весь период») остаётся 1px запаса при окне 1150.
    # Любая мелочь — компактный режим, третья строка в имени — и содержимое
    # уезжает во внутреннюю прокрутку карточки.
    "dynamics": (4, 7),
    "bar": (12, 6), "line": (12, 6), "pie": (6, 6), "waterfall": (6, 6),
    "compare": (12, 8), "cross_dataset_compare": (12, 8), "yoy": (12, 6),
    "heatmap": (6, 7), "pivot": (12, 6), "table": (12, 6), "matrix": (12, 7),
    "funnel": (6, 7), "status_grid": (6, 6), "objects_compare": (6, 7),
    # Полосы: строка на пару «план + факт». Высота растёт с числом строк, её
    # считает `bullet_height` — здесь запасное значение на 3 строки.
    "bullet": (6, 7),
    # Рейтинг: высота растёт с числом показанных строк, её считает
    # `ranked_height` — здесь запасное значение на топ-5 без антитопа.
    "ranked": (6, 8),
    # Мини-графики — вид табличный: строка формы, линия и число в ряд. В
    # половине ряда линия сжимается до нечитаемого штриха.
    "spark_table": (12, 8),
    # Термометр: два столбика («выполнено» против «прошло срока»), под ними
    # «нужно в день» и прогноз — в семи рядах прогноз уезжает в прокрутку.
    "thermometer": (4, 9),
    "text": (12, 2), "image": (6, 5),
}


# Размер карточки берём ИЗ ТАБЛИЦЫ, а не числом на месте: раньше он был вписан
# и в WIDGET_SIZE, и в саму сборку, поэтому при изменении одного места второе
# молча оставалось прежним — пересобранная страница выглядела не так, как
# подогнанная кнопкой «↕ Подогнать размеры».
KPI_W, KPI_H = WIDGET_SIZE["kpi"]

# Сколько пар «план + факт» нужно, чтобы полосы имели смысл. На ОДНОЙ паре
# полоса — это тот же «План-факт», только без прогноза: сравнивать не с чем,
# а ради чего полосы и берут — сравнение показателей между собой.
MIN_BULLET_ROWS = 2


def bullet_height(rows: int) -> int:
    """Высота карточки полос: шапка плюс ряд на каждую пару.

    Тот же приём, что у матрицы (`matrix_height`): высота виджета, у которого
    число строк известно заранее, не может быть константой — иначе часть строк
    молча уезжает во внутреннюю прокрутку, то есть пропадает ровно то, ради чего
    виджет и ставили.
    """
    return min(24, 3 + max(1, rows))


# Рейтинг по умолчанию: пять строк сверху и пять снизу.
RANKED_TOP_N = 5


def ranked_rows_shown(cfg: dict) -> int:
    """Сколько строк покажет рейтинг — по его же настройке.

    Точное число строк формы заранее неизвестно (оно в данных, а не в
    конфигурации), поэтому берём верхнюю оценку: топ плюс антитоп. Та же
    договорённость, что у матрицы, — обе стороны (сборка и «↕ Подогнать
    размеры») считают высоту ОДНИМ правилом.
    """
    top = max(1, int(cfg.get("top_n") or RANKED_TOP_N))
    return top * 2 if cfg.get("bottom", True) else top


def ranked_height(rows: int) -> int:
    """Высота карточки рейтинга: шапка, строки и подпись под ними."""
    return min(24, 4 + max(1, rows))


def matrix_height(field_count: int) -> int:
    """Высота матрицы «показатель × дата» — по числу строк, которые она покажет.

    У формы заказчика показателей тринадцать, и в стандартные ряды помещаются
    две строки: остальное уезжает во внутреннюю прокрутку карточки, ради
    которой матрицу и не берут.

    Запас в пять рядов, а не в четыре: замер в свободной сетке показал, что при
    `4 + N` матрице на 13 показателей не хватает ровно 21px (шапка таблицы,
    строка итога и подпись источника). В «потоке» этого не видно — там высота
    считается по содержимому.
    """
    return max(8, min(24, 5 + (field_count or 6)))


def _content_height(widget: dict, default_h: int) -> int:
    """Высота, зависящая от СОДЕРЖИМОГО виджета, а не только от его типа.

    Таких виджетов два: матрица (строк столько, сколько выбрано показателей) и
    полосы «план и факт» (строка на каждую пару). Правило вынесено сюда, чтобы
    кнопка «↕ Подогнать размеры» и авто-сборка считали высоту ОДИНАКОВО: раньше
    сборка растягивала матрицу по числу показателей, а подгонка тут же ужимала
    её обратно до табличного размера из `WIDGET_SIZE` — то есть кнопка молча
    ломала то, что собрал мастер.
    """
    kind = widget.get("widget_type")
    if kind not in ("matrix", "bullet", "ranked"):
        return default_h
    cfg = widget.get("config") or {}
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg)
        except (TypeError, ValueError):
            cfg = {}
    if kind == "bullet":
        return bullet_height(len(cfg.get("pairs") or []))
    if kind == "ranked":
        return ranked_height(ranked_rows_shown(cfg))
    # Разрез по строкам формы: сколько их будет, заранее неизвестно — берём ту
    # же оценку в шесть строк, что и авто-сборка, чтобы обе стороны считали
    # одинаково.
    return matrix_height(len(cfg.get("value_fields") or []))


def fit_layout(widgets: list) -> list:
    """Пересчёт раскладки страницы: каждому виджету — размер по его типу,
    порядок сохраняется, ряд заполняется слева направо.

    Нужна старым дашбордам: собранные до перехода авто-сборки на крупные
    карточки, они держат виджеты 3×3, где имя показателя обрезается, а число
    не помещается вовсе. Растягивать полтора десятка карточек мышью по одной —
    занятие на полчаса.
    """
    out: list = []
    x = y = row_h = 0
    for w in widgets:
        width, height = WIDGET_SIZE.get(w["widget_type"], (4, 5))
        height = _content_height(w, height)
        if x + width > 12:            # в ряду не осталось места — новая строка
            x, y, row_h = 0, y + row_h, 0
        out.append({"id": str(w["id"]), "position_x": x, "position_y": y,
                    "width": width, "height": height})
        x += width
        row_h = max(row_h, height)
    return out


def _grid_rows(items: list, start_y: int, per_row: int, width: int, height: int):
    """Позиции карточек: по `per_row` в ряд, ряды идут вниз от `start_y`.

    Высота в пределах одной пачки одинаковая — карточки разной высоты в одном
    ряду наложились бы друг на друга (y считается по номеру ряда).
    """
    for i, item in enumerate(items):
        yield item, {"position_x": (i % per_row) * width,
                     "position_y": start_y + (i // per_row) * height,
                     "width": width, "height": height}


def _rows_height(count: int, per_row: int, height: int) -> int:
    return ((count + per_row - 1) // per_row) * height if count else 0


# --------------------------------------------------------------------------- #
# Авто-сборка дашборда из объекта (rule-based, не ИИ)
# --------------------------------------------------------------------------- #
async def _dataset_numeric_fields(conn, org_id, dataset_code: str) -> List[dict]:
    rel = await mr._active_release(conn, org_id, dataset_code)
    if rel is None:
        return []
    rows = await conn.fetch(
        "select drf.canonical_field_code as code, coalesce(cf.name, drf.canonical_field_code) as name "
        "from dataset_release_fields drf "
        "left join canonical_fields cf on cf.code=drf.canonical_field_code "
        "  and cf.object_id=(select object_id from dataset_releases where id=$1) "
        "where drf.dataset_release_id=$1 and coalesce(cf.data_type,'text')='number' "
        "order by drf.canonical_field_code", rel)
    return [dict(r) for r in rows]


def _spec_signature(widget_type: str, cfg: dict):
    """Ключ дедупликации предложения: тип + датасет + набор полей (без учёта
    порядка/названия виджета) — «то же самое», даже если названо иначе."""
    if widget_type == "plan_fact":
        fields = tuple(sorted(x for x in (cfg.get("plan_field"), cfg.get("fact_field")) if x))
    elif cfg.get("value_fields"):
        fields = tuple(sorted(cfg["value_fields"]))
    elif cfg.get("value_field"):
        fields = (cfg["value_field"],)
    else:
        fields = ()
    return (widget_type, cfg.get("dataset_code"), fields)


async def _existing_widget_signatures(conn, org_id, dataset_code: str) -> set:
    """Волна «рекомендации»: сигнатуры УЖЕ построенных виджетов по этому
    датасету — ОРГАНИЗАЦИОННО-широкий поиск (не только текущий дашборд), т.к.
    dataset_code однозначно принадлежит одному объекту — так предложения не
    повторяют то, что уже собрано где угодно для этого же объекта/датасета."""
    rows = await conn.fetch(
        "select widget_type, config from widgets where organization_id=$1 and config->>'dataset_code'=$2",
        org_id, dataset_code)
    return {_spec_signature(r["widget_type"], _cfg(r)) for r in rows}


async def suggest_widgets(conn, org_id, dataset_code: str) -> dict:
    """Подсказки «что собрать» под датасет: готовые спецификации виджетов
    (KPI по каждому числовому полю, график по строкам, динамика при >1 периода,
    сравнение/план-факт при ≥2 полях, таблица-первичка). Пользователь выбирает.
    Delta-aware (рекомендательная система, 2026-08-04): то, что уже построено
    для этого датасета — где угодно в организации — из предложений убирается,
    чтобы не предлагать заново то же самое."""
    fields = await _dataset_numeric_fields(conn, org_id, dataset_code)
    if not fields:
        raise DashboardError("У датасета нет числовых полей — сначала распознайте документ")
    dsname = await _dataset_display_name(conn, org_id, dataset_code)
    periods = await conn.fetchval(
        "select count(distinct reporting_period_start) from dataset_releases "
        "where organization_id=$1 and code=$2 and status<>'superseded'", org_id, dataset_code) or 0

    specs: List[dict] = []
    for f in fields:
        specs.append({"name": f"Σ {f['name']}", "widget_type": "kpi",
                      "config": {"dataset_code": dataset_code, "value_field": f["code"]}, "width": 3, "height": 3})
    f0 = fields[0]
    specs.append({"name": f"{f0['name']} по строкам", "widget_type": "bar",
                  "config": {"dataset_code": dataset_code, "value_field": f0["code"]}, "width": 5, "height": 6})
    specs.append({"name": f"Водопад: {f0['name']}", "widget_type": "waterfall",
                  "config": {"dataset_code": dataset_code, "value_field": f0["code"]}, "width": 6, "height": 6})
    if periods > 1:
        specs.append({"name": f"Динамика: {f0['name']}", "widget_type": "dynamics",
                      "config": {"dataset_code": dataset_code, "value_field": f0["code"]}, "width": 6, "height": 6})
    if len(fields) >= 2:
        specs.append({"name": "Сравнение полей", "widget_type": "compare",
                      "config": {"dataset_code": dataset_code, "value_fields": [f["code"] for f in fields[:4]], "viz": "bar"},
                      "width": 6, "height": 7})
        specs.append({"name": "Тепловая карта", "widget_type": "heatmap",
                      "config": {"dataset_code": dataset_code, "value_fields": [f["code"] for f in fields[:6]]},
                      "width": 6, "height": 7})
        specs.append({"name": "Сводная таблица", "widget_type": "pivot",
                      "config": {"dataset_code": dataset_code, "value_fields": [f["code"] for f in fields[:6]]},
                      "width": 6, "height": 6})
        specs.append({"name": f"План/факт: {fields[0]['name']} / {fields[1]['name']}", "widget_type": "plan_fact",
                      "config": {"dataset_code": dataset_code, "plan_field": fields[0]["code"], "fact_field": fields[1]["code"]},
                      "width": 4, "height": 5})
    specs.append({"name": f"{dsname}: таблица", "widget_type": "table",
                  "config": {"dataset_code": dataset_code}, "width": 6, "height": 6})

    existing = await _existing_widget_signatures(conn, org_id, dataset_code)
    delta = [s for s in specs if _spec_signature(s["widget_type"], s["config"]) not in existing]
    return {"specs": delta, "total_candidates": len(specs), "already_built": len(specs) - len(delta)}


# --------------------------------------------------------------------------- #
# Авто-сборка: сбор данных → план раскладки → создание
#
# Раскладка считается ОДНОЙ функцией `plan_auto_build`, а предпросмотр и
# создание лишь по-разному ей пользуются. Иначе «будет создано N виджетов»
# рано или поздно разошлось бы с тем, что получилось на самом деле, — та же
# ловушка, из-за которой предпросмотр разметки считают тем же кодом, что и
# выпуск датасета.
# --------------------------------------------------------------------------- #
# Общие блоки дашборда. «kpi» и «dynamics» остались для совместимости выбора,
# но вид конкретного показателя задаётся отдельно (VIEWS) — так человек может
# сказать «этот числом, этот трендом», а не только «все или никак».
BLOCKS = ["plan_fact", "kpi", "compare", "dynamics", "matrix", "bar", "table", "by_meaning"]


async def document_release_info(conn, org_id, document_id: str) -> dict:
    """Что выпущено из конкретного файла: код набора и отчётная дата.

    Нужно для сборки «по этому отчёту»: человек выбирает объект → папку →
    файл, и дашборд должен показывать именно его цифры, а не всё, что есть в
    объекте.
    """
    row = await conn.fetchrow(
        "select r.code, r.reporting_period_start as period, d.original_filename, d.folder_id "
        "from dataset_releases r "
        "join document_versions v on v.id=r.source_document_version_id "
        "join documents d on d.id=v.document_id "
        "where d.id=$1::uuid and r.organization_id=$2 and r.status<>'superseded' "
        "order by r.created_at desc limit 1", document_id, org_id)
    if row is None:
        raise DashboardError(
            "Из этого файла ещё не выпускали данные — сначала разметьте его и выпустите датасет")
    return {"code": row["code"],
            "period": row["period"].isoformat() if row["period"] else None,
            "filename": row["original_filename"]}


# Дата в конце названия выпуска: «Показатели MAX 22.07.2026», «Форма 2026-07-22».
_TRAILING_DATE = re.compile(r"[\s,·—-]*\(?\b(\d{2}[.\-/]\d{2}[.\-/]\d{2,4}|\d{4}-\d{2}-\d{2})\b\)?\s*$")


def form_title(name: str) -> str:
    """Название ФОРМЫ для заголовка виджета — без отчётной даты.

    Заголовок виджета фиксируется в момент сборки и больше не меняется, а
    данные обновляются. Поэтому любая дата в заголовке рано или поздно
    устаревает: виджет назывался бы «Показатели MAX 29.06.2026», показывая
    данные за 22.07.2026. Живая и честная дата у виджета уже есть — строка
    «🕓 данные на …» под ним, она считается при каждом открытии.

    Дату убираем ТОЛЬКО из хвоста: «Отчёт за 2026 год» — это часть имени
    формы, а не отчётная дата.
    """
    raw = (name or "").strip()
    # Имя выпуска у заказчика — это имя файла: «Приложение_к_Протоколу_новая_
    # форма 19.08.2026.xlsx». В заголовке виджета расширение и подчёркивания
    # выглядят машинным следом, а руководителю нужно название формы.
    raw = re.sub(r"\.(xlsx|xls|csv|pdf|docx)$", "", raw, flags=re.IGNORECASE)
    raw = raw.replace("_", " ")
    raw = re.sub(r"\s{2,}", " ", raw).strip()
    cleaned = _TRAILING_DATE.sub("", raw).strip(" ,·—-")
    return cleaned or (name or "").strip()


async def _dataset_display_name(conn, org_id, code: str) -> str:
    """Как называется набор данных сейчас — по ПОСЛЕДНЕМУ отчёту.

    Раньше здесь стоял `max(name)` — алфавитный максимум по названиям
    выпусков. У формы, названной с датой, он давал не последний отчёт, а
    строку, которая «больше» посимвольно: при выпусках до 22.07.2026
    выигрывало «Показатели MAX 29.06.2026» (сравниваются символы «2», «9»
    против «2», «2»).
    """
    name = await conn.fetchval(
        "select name from dataset_releases where organization_id=$1 and code=$2 "
        "and status<>'superseded' "
        "order by reporting_period_start desc nulls last, created_at desc limit 1",
        org_id, code)
    return form_title(name) if name else code


async def collect_object_datasets(conn, org_id, object_id: str,
                                  only_code: Optional[str] = None) -> list:
    """Наборы данных объекта с их показателями — основа и плана, и мастера.

    `only_code` сужает выбор до одного набора: так собирается дашборд по
    конкретному файлу (у файла всегда один код — это его форма).
    """
    rows = await conn.fetch(
        "select code, count(distinct reporting_period_start) as periods, "
        "  count(*) as releases "
        "from dataset_releases where organization_id=$1 and object_id=$2::uuid and status<>'superseded' "
        + ("and code=$3 " if only_code else "")
        + "group by code order by max(created_at) desc",
        *([org_id, object_id, only_code] if only_code else [org_id, object_id]))
    out = []
    for d in rows:
        fields = await _dataset_numeric_fields(conn, org_id, d["code"])
        # Сами отчётные даты нужны мастеру: по ним человек выбирает недели,
        # для которых нужны отдельные страницы (этап 3).
        dates = await conn.fetch(
            "select distinct reporting_period_start as p from dataset_releases "
            "where organization_id=$1 and code=$2 and status<>'superseded' "
            "and reporting_period_start is not null order by 1 desc limit 60",
            org_id, d["code"])
        # Сколько строк в форме (районов/отделений) — по последнему выпуску.
        # От этого зависит, есть ли смысл в матрице «строка × дата»: у формы с
        # единственной строкой она дословно повторяет «Динамику».
        n_rows = await conn.fetchval(
            "select count(distinct row_label) from dataset_values where dataset_release_id = ("
            "  select id from dataset_releases where organization_id=$1 and code=$2 "
            "  and status<>'superseded' order by reporting_period_start desc nulls last, created_at desc limit 1)",
            org_id, d["code"])
        # Суммы по показателям за последний выпуск. Нужны правилу воронки: без
        # чисел она построилась бы по одному словарю и выдала бы за ступени
        # несопоставимые сущности («уведомления → обращения»). Один запрос на
        # набор данных, поэтому дешевле, чем считать каждый показатель отдельно.
        sums = await conn.fetch(
            "select v.canonical_field_code as code, sum(v.value_number) as total "
            "from dataset_values v where v.dataset_release_id = ("
            "  select id from dataset_releases where organization_id=$1 and code=$2 "
            "  and status<>'superseded' "
            "  order by reporting_period_start desc nulls last, created_at desc limit 1) "
            "group by 1", org_id, d["code"])
        # Объём показателя за ВСЮ историю выпусков — по нему мастер решает, какие
        # показатели вынести на дашборд, когда их больше, чем туда помещается.
        #
        # Отдельным запросом от `sums`, а не переиспользованием: тот считает
        # ПОСЛЕДНИЙ выпуск, и этого достаточно для проверки вложенности воронки,
        # но негодно для выбора. Реальный случай (РЦО, 02.09.2026): последним
        # листом книги оказалась пустая заготовка ещё не заполненного дня — по
        # ней все показатели равны нулю, и сортировка по объёму выбрала бы
        # наугад ровно так же, как порядок заведения.
        #
        # abs(): объём — это «сколько через показатель проходит», и минус его не
        # уменьшает. Знак здесь ни при чём, а взаимное вычитание значений скрыло
        # бы нагруженную графу.
        volumes = await conn.fetch(
            "select v.canonical_field_code as code, sum(abs(v.value_number)) as total "
            "from dataset_values v where v.dataset_release_id in ("
            "  select id from dataset_releases where organization_id=$1 and code=$2 "
            "  and status<>'superseded') "
            "group by 1", org_id, d["code"])
        out.append({
            "code": d["code"], "name": await _dataset_display_name(conn, org_id, d["code"]),
            "periods": d["periods"] or 0, "releases": d["releases"] or 0,
            "rows": int(n_rows or 0),
            "fields": fields,
            "period_dates": [r["p"].isoformat() for r in dates],
            "sums": {r["code"]: float(r["total"]) for r in sums if r["total"] is not None},
            "volumes": {r["code"]: float(r["total"]) for r in volumes if r["total"] is not None},
        })
    return out


# Вид показателя на дашборде. Раньше все получали одинаковую карточку; теперь
# вид подбирается по РОЛИ показателя, которую система и так разбирает в имени
# столбца госформы («Показатель · Роль · Разрез»).
VIEWS = ["kpi", "dynamics", "both", "none"]
# Мастер собирает страницу в режиме «поток»: он и так расставляет виджеты по
# типу, а «поток» пересчитывает то же самое при каждой отрисовке — собранная
# страница не может поехать и не оставляет дыр, а на широком мониторе сама
# становится плотнее. Человек переключает страницу на свободную сетку одной
# кнопкой; уже собранные страницы миграция не трогает.
AUTO_LAYOUT_MODE = "flow"
PAGE_OVERVIEW, PAGE_DYNAMICS, PAGE_RAW = "Обзор", "Динамика", "Первичные данные"
PAGE_PERIOD_PREFIX = "Отчёт за"
# Потолок страниц-срезов: каждая страница — это ещё десяток запросов данных,
# а дашборд из полусотни вкладок невозможно листать.
MAX_AUTO_PERIOD_PAGES = 8
# Сколько отчётов показывает собранная матрица. То же число, что и умолчание
# самого виджета: собранная мастером страница не должна отличаться от той, где
# матрицу добавили руками.
MATRIX_PERIODS = 12
# Сколько показателей помещается в матрицу «показатель × дата», не превращая её
# в стену: у госформы их полтора десятка, и все они осмысленны.
MATRIX_FIELDS = 20
# Сколько трендов оставить рядом с матрицей: она уже отвечает «что где было»,
# а график нужен, чтобы увидеть ФОРМУ движения у главных показателей.
MAX_TRENDS_WITH_MATRIX = 4


def default_view(field_name: str, has_periods: bool) -> str:
    """Как показать показатель, если человек не выбрал сам.

    Число отвечает «сколько сейчас», тренд — «куда идёт», и второй вопрос
    руководитель задаёт по КАЖДОМУ показателю, а не только по недельному.
    Поэтому при нескольких отчётных периодах показатель получает и карточку, и
    тренд (запрос заказчика: «показывать динамику по всем показателям, по
    которым она есть»). Раньше тренд доставался только разрезу «за отчётную
    неделю», и на странице «Динамика» половина показателей отсутствовала без
    всякой причины — данные для них были.

    Без нескольких периодов тренда быть не может: рисовать линию по одной
    точке — значит показать пустоту вместо ответа.

    Вид всё равно остаётся выбором человека: в мастере у каждого показателя
    есть переключатель, и снятый тренд не вернётся сам.
    """
    return "both" if has_periods else "kpi"


# --------------------------------------------------------------------------- #
# Выбор вида виджета ПО СМЫСЛУ ДАННЫХ
#
# До этого авто-сборка ставила почти одно и то же: карточки, тренды, таблица —
# восемь видов из двадцати одного. Дашборды выходили одинаковыми не потому, что
# видов мало, а потому, что мастер не смотрел, ЧТО в данных.
#
# Общее правило для всех проверок ниже: правило либо уверенно срабатывает, либо
# МОЛЧИТ. Виджет, поставленный «на всякий случай», показывает правдоподобную
# неправду — это дороже, чем его отсутствие. Поэтому у каждого правила есть
# порог, ниже которого оно не ставит ничего.
# --------------------------------------------------------------------------- #

# Ступени воронки: (слова целого, слова части). Тот же словарь, что у подбора
# метрик (`metrics/data_suggestions._FUNNEL_PAIRS`) — система не должна
# понимать «отправлено → доставлено» двумя разными способами.
FUNNEL_STAGES = [
    ("отправленн", "направленн", "выгруженн"),
    ("доставленн", "врученн", "полученн"),
    ("обращени", "обратилось", "заявлен"),
    ("записавших", "записал", "зарегистрирова"),
]
# Меньше трёх ступеней воронка не строится: два этапа — это обычный процент,
# и «Доля доставленных» отвечает на тот же вопрос точнее.
MIN_FUNNEL_STAGES = 3
# Светофору нужно столько строк, чтобы плитки читались как карта состояния.
# На двух-трёх строках он хуже обычных карточек.
MIN_ROWS_STATUS_GRID = 6
# Круговая честна только на немногих долях: на два десятка секторов подписи
# слипаются, и сравнить их глазами нельзя.
PIE_ROWS = (3, 7)
# Тепловая карта имеет смысл, когда есть и строки, и с чем их сравнивать.
MIN_ROWS_HEATMAP = 4
MIN_FIELDS_HEATMAP = 2
# Водопад показывает вклад периодов — нужен ряд, а не пара точек.
MIN_PERIODS_WATERFALL = 3
# Термометров на форму: у каждого свой срок и свой показатель, но первый экран
# не должен состоять из них одних.
MAX_AUTO_THERMOMETERS = 2
# Рейтинг нужен там, где строк слишком много, чтобы читать их подряд. Порог
# выше, чем у светофора (6): на восьми отделениях список повторил бы плитки,
# а на шестидесяти трёх плитки превращаются в стену, и «кто в хвосте» из них
# уже не вычитывается.
MIN_ROWS_RANKED = 10
# Мини-графики: строк должно быть несколько (на одной «Динамика» отвечает
# лучше и подробнее), а отчётов — хотя бы три: на двух точках линия
# вырождается в отрезок и формы движения не показывает вовсе.
MIN_ROWS_SPARK = 4
MIN_PERIODS_SPARK = 3


# Куда какой вид попадает по смыслу страницы: «как сейчас» / «как менялось» /
# «откуда цифры». Иначе воронка оказалась бы среди первичных данных, а водопад
# на «Обзоре» — там, где его никто не ищет.
BY_MEANING_PAGE = {
    "funnel": PAGE_OVERVIEW, "status_grid": PAGE_OVERVIEW, "ranked": PAGE_OVERVIEW,
    "bullet": PAGE_OVERVIEW, "thermometer": PAGE_OVERVIEW,
    "spark_table": PAGE_DYNAMICS,
    "waterfall": PAGE_DYNAMICS, "yoy": PAGE_DYNAMICS,
    "pie": PAGE_RAW, "heatmap": PAGE_RAW,
}
BY_MEANING_TITLE = {
    "funnel": "Воронка: где теряются",
    "status_grid": "{name}: по отделениям",
    "waterfall": "{name}: вклад периодов",
    "yoy": "{name}: год к году",
    "pie": "{name}: доли строк",
    "heatmap": "Тепловая карта показателей",
    "bullet": "План и факт: все показатели",
    "ranked": "{name}: кто впереди и кто в хвосте",
    "spark_table": "{name}: как двигалась каждая строка",
    "thermometer": "{name}: успеваем ли к сроку",
}


# Месяцы в том виде, в каком они пишутся в госформах («до 1 сентября 2026 г.»).
# Ключ — начало слова: падеж («сентября») и сокращение («сент.») дают одно и то
# же начало, а вот «март» и «мая» различаются с первых букв, поэтому пересечения
# между ключами нет.
_RU_MONTHS = {"январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
              "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12}
_DEADLINE_WORDS = re.compile(r"\bдо\s+(\d{1,2})\s+([а-яё]+)\s+(\d{4})", re.I)
_DEADLINE_DIGITS = re.compile(r"\b(?:до|к)\s+(\d{1,2})\.(\d{1,2})\.(\d{4})", re.I)


def deadline_from_name(name: str):
    """Срок, если он назван прямо в имени графы плана. Иначе — None.

    В госформе план почти всегда подписан сроком: «План (до 1 сентября
    2026 г.)». Пока эта дата лежит только в тексте, «успеваем ли» приходится
    считать в уме, сопоставляя проценты с календарём.

    Правило то же, что у остальных видов «по смыслу»: разобрали дату уверенно —
    ставим термометр, не разобрали — молчим. Выдуманный срок здесь хуже
    отсутствующего: по нему считается «опережение/отставание», и ошибка в дате
    превращается в ложную тревогу на первом экране руководителя.
    """
    from datetime import date

    m = _DEADLINE_DIGITS.search(name or "")
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    m = _DEADLINE_WORDS.search(name or "")
    if not m:
        return None
    word = m.group(2).lower()
    # «март» проверяем раньше «ма»: иначе март стал бы маем.
    for stem in sorted(_RU_MONTHS, key=len, reverse=True):
        if word.startswith(stem):
            try:
                return date(int(m.group(3)), _RU_MONTHS[stem], int(m.group(1)))
            except ValueError:
                return None
    return None


def _is_cumulative(name: str) -> bool:
    """Накопительный итог: у него вклад периодов и виден водопадом."""
    return bool(re.search(r"нарастающ|накопительн|итог", name or "", re.I))


def _funnel_chain(fields: list, values: Optional[dict] = None) -> list:
    """Поля, образующие настоящую воронку: ступени по словарю, вложенные друг в
    друга по величине.

    Проверяем ОБА условия, и это принципиально. Только по словам получилась бы
    воронка из несопоставимых сущностей; только по числам — «отправлено
    уведомлений 2,5 млн → обращений 1 млн», где второе не является частью
    первого, просто число меньше. У заказчика на форме МАХ ровно этот случай,
    поэтому там воронка не строится — и это верное поведение.
    """
    stage_of: dict = {}
    for f in fields:
        subj = _split_name(f["name"]).get("subject", "").lower()
        for i, words in enumerate(FUNNEL_STAGES):
            if any(w in subj for w in words):
                stage_of.setdefault(i, f)
                break
    chain = [stage_of[i] for i in sorted(stage_of)]
    if len(chain) < MIN_FUNNEL_STAGES:
        return []
    # Без значений воронку НЕ строим вовсе. Проверка «закрыта по умолчанию»:
    # одного словаря мало — на форме заказчика он даёт цепочку
    # «отправлено → доставлено → обращения → записались», где обращения не
    # являются частью уведомлений. Такая воронка выглядит убедительно и врёт.
    if not values:
        return []
    seq = [values.get(f["code"]) for f in chain]
    if any(v is None for v in seq):
        return []
    sums = [float(v) for v in seq if v is not None]
    if any(sums[i] < sums[i + 1] for i in range(len(sums) - 1)):
        return []              # не вкладываются — значит это не ступени
    return chain


def by_meaning_specs(fields: list, rows: int, periods: int, first_period: str = "",
                     last_period: str = "", values: Optional[dict] = None,
                     volumes: Optional[dict] = None) -> list:
    """Дополнительные виды виджетов, подобранные под СМЫСЛ данных.

    Возвращает список {kind, config-заготовка} — без места на сетке: раскладку
    расставляет вызывающая сторона, как и для остальных блоков.
    """
    out: list = []
    facts = [f for f in fields
             if _split_name(f["name"]).get("role") != "plan" and not is_share(f["name"])]
    main = [f for f in facts if _is_main_slice(_split_name(f["name"]).get("slice", ""))] or facts
    # Виды «по смыслу» берут ОДНУ графу (`main[0]`) — светофор, рейтинг,
    # мини-графики, водопад. Брать первую по порядку заведения здесь так же
    # неверно, как и в отборе карточек: на форме РЦО это дало рейтинг по
    # редкой услуге с итогом 0, тогда как «ИТОГО · Принято» давало 5 943 в
    # день. Сортируем по объёму, если он замерен.
    if volumes:
        main = sorted(main, key=lambda f: -volumes.get(f["code"], 0.0))

    chain = _funnel_chain(main, values)
    if chain:
        out.append({"kind": "funnel", "fields": chain})

    if rows >= MIN_ROWS_STATUS_GRID and main:
        # Один показатель по многим строкам: столбчатый график на 63 полоски
        # нечитаем, а плитка на отделение отвечает «где хорошо, где плохо».
        out.append({"kind": "status_grid", "fields": [main[0]]})

    if rows >= MIN_ROWS_SPARK and periods >= MIN_PERIODS_SPARK and main:
        # Рейтинг отвечает «кто первый», светофор — «у кого плохо», а этот вид
        # — «как каждый двигался». Матрица отвечает тем же разрезом, но
        # числами: на двенадцати столбцах она не помещается, а линия помещается
        # и при шестидесяти строках.
        out.append({"kind": "spark_table", "fields": [main[0]]})

    if rows >= MIN_ROWS_RANKED and main:
        # Светофор отвечает «где плохо» цветом, рейтинг — «кто первый и кто
        # последний» порядком. На шести отделениях хватает первого, на
        # шестидесяти трёх без второго не обойтись.
        out.append({"kind": "ranked", "fields": [main[0]],
                    "height": ranked_height(ranked_rows_shown({}))})

    if PIE_ROWS[0] <= rows <= PIE_ROWS[1] and main:
        out.append({"kind": "pie", "fields": [main[0]]})

    if rows >= MIN_ROWS_HEATMAP and len(main) >= MIN_FIELDS_HEATMAP:
        out.append({"kind": "heatmap", "fields": main[:6]})

    cum = [f for f in main if _is_cumulative(f["name"])]
    if cum and periods >= MIN_PERIODS_WATERFALL:
        # Вклад каждой недели в накопительный итог: линия показывает уровень,
        # водопад — за счёт чего он такой.
        out.append({"kind": "waterfall", "fields": [cum[0]]})

    # Год к году — только если данные ДЕЙСТВИТЕЛЬНО пересекают два календарных
    # года: иначе виджет сравнивал бы год сам с собой.
    if main and first_period[:4] and last_period[:4] and first_period[:4] != last_period[:4]:
        out.append({"kind": "yoy", "fields": [main[0]]})

    # Полосы «план и факт»: одна карточка вместо пары-тройки отдельных.
    # Ставим ТОЛЬКО при нескольких парах — на одной паре полоса это тот же
    # «План-факт», только без прогноза.
    pairs = _plan_fact_pairs(fields)
    if len(pairs) >= MIN_BULLET_ROWS:
        out.append({"kind": "bullet", "fields": [f for _, f in pairs],
                    "config": {"pairs": [{"plan_field": pl["code"], "fact_field": fa["code"]}
                                         for pl, fa in pairs]},
                    "height": bullet_height(len(pairs))})

    # Термометр к сроку — только там, где срок НАЗВАН в имени графы плана.
    # Спрашивать его у человека в мастере значило бы задавать вопрос, ответ на
    # который уже написан в форме; выдумывать — ставить на первый экран
    # «отставание», посчитанное от даты, которой никто не назначал.
    for plan_f, fact_f in pairs[:MAX_AUTO_THERMOMETERS]:
        due = deadline_from_name(plan_f["name"])
        if due is None:
            continue
        out.append({"kind": "thermometer", "fields": [fact_f],
                    "config": {"plan_field": plan_f["code"], "fact_field": fact_f["code"],
                               "deadline": due.isoformat()}})

    return out


def _plan_fact_pairs(fields: list) -> list:
    """Пары «План + Факт» одного показателя в основном разрезе.

    Две карточки рядом заставляют считать процент в уме, а виджет «План-факт»
    показывает полосу выполнения сразу. Пары ищем только в ОСНОВНОМ разрезе:
    план в форме задан накопительный («до 1 сентября»), и сравнивать его с
    недельным фактом было бы заведомо неверно.
    """
    # План берём в ЛЮБОМ разрезе: он и так задан накопительно («до 1 сентября»),
    # а его собственная подпись под «нарастающим итогом» не подходит. Требование
    # основного разреза относится к ФАКТУ — иначе план сравнивался бы с недельным
    # или месячным срезом, что заведомо неверно. Правило то же, что в подборе
    # метрик (metrics/data_suggestions), чтобы система не противоречила себе.
    plans: dict = {}
    for f in fields:
        p = _split_name(f["name"])
        if p.get("role") == "plan":
            plans[_subject_key(p.get("subject", ""))] = f
    out = []
    for f in fields:
        p = _split_name(f["name"])
        if p.get("role") != "fact" or not _is_main_slice(p.get("slice", "")):
            continue
        plan = plans.get(_subject_key(p.get("subject", "")))
        if plan:
            out.append((plan, f))
    return out


def _pick_shown(fields: list, volumes: dict) -> list:
    """Какие показатели вынести на дашборд, когда их больше, чем помещается.

    🔴 Раньше брались ПЕРВЫЕ по порядку заведения — то есть по сути наугад.
    На форме РЦО из 326 граф это дало дашборд из редких услуг: даже в рабочий
    день у выбранной графы 62 строки и итог 0, а «ИТОГО · Принято» (5 943 за
    день) на дашборд не попало вовсе.

    Порядок заведения полей — это порядок столбцов в файле, и он ничего не
    говорит о важности. Объём говорит: показатель, через который проходят
    тысячи обращений, и показатель с нулём за полгода — разные новости.

    На узкой форме порядок НЕ меняется: пересортировка там ничего не улучшает
    (помещаются все), а привычный порядок столбцов файла — сам по себе
    осмысленный порядок, ломать его без выгоды незачем.
    """
    if len(fields) <= MAX_AUTO_KPI:
        return fields
    # Показатели без замеренного объёма уходят в конец, а не наверх: у них
    # объём неизвестен, и ставить их впереди заведомо нагруженных нельзя.
    ranked = sorted(fields, key=lambda f: -volumes.get(f["code"], 0.0))
    return ranked[:MAX_AUTO_KPI]


def plan_auto_build(datasets: list, selection: Optional[dict] = None,
                    alerts: bool = True, pin_period: Optional[str] = None) -> list:
    """Что именно будет создано — список виджетов с местом на сетке и страницей.

    `selection` = {code: {"fields": [коды], "blocks": [виды], "views": {код: вид}}}.
    Не передан — берём всё с автоматически подобранными видами.
    `alerts` — проставлять ли пороги невыполнения плана (галочка в мастере).
    `pin_period` — отчётная дата, к которой ЗАКРЕПЛЯЮТСЯ виджеты: так собирается
    дашборд по конкретному файлу. Человек выбрал отчёт за 22.07 — значит и
    через неделю дашборд обязан показывать 22.07, иначе это будет уже другой
    отчёт под тем же названием. Виджет с закреплённой датой честно подписан
    «📌 срез · не обновляется» (см. `period_locked`).

    Страницы разделены по смыслу: «Обзор» отвечает на «как сейчас», «Динамика» —
    на «как менялось», «Первичные данные» — «откуда цифры». Одна длинная страница
    со всем сразу читалась плохо, да и данные грузятся постранично.
    """
    specs: list = []
    ov_y = dyn_y = raw_y = 0
    for d in datasets:
        code, dsname = d["code"], d["name"]
        sel = (selection or {}).get(code)
        if selection is not None and sel is None:
            continue  # набор данных снят галочкой целиком
        want_fields = set(sel["fields"]) if sel and sel.get("fields") is not None else None
        blocks = set(sel["blocks"]) if sel and sel.get("blocks") is not None else set(BLOCKS)
        views = (sel or {}).get("views") or {}

        fields = [f for f in d["fields"] if want_fields is None or f["code"] in want_fields]
        if not fields:
            continue
        shown = _pick_shown(fields, d.get("volumes") or {})
        has_dyn = d["periods"] > 1

        # views/has_dyn связываем явно: замыкание на переменную цикла — классическая
        # ловушка (в следующей итерации функция увидела бы уже другой набор данных).
        def view_of(f, views=views, has_dyn=has_dyn):
            v = views.get(f["code"]) or default_view(f["name"], has_dyn)
            return v if v in VIEWS else "kpi"

        # ── Обзор: план-факт полосой, остальные — карточками, снизу сравнение ──
        # Пары «план + факт» нужны двум блокам сразу, поэтому считаем их до
        # обоих: при нескольких парах их показывают ПОЛОСЫ одной карточкой, и
        # плодить рядом столько же отдельных «План-фактов» значило бы дважды
        # ответить на один вопрос и занять первый экран целиком.
        pf_pairs = _plan_fact_pairs(shown)
        bullet_instead = "by_meaning" in blocks and len(pf_pairs) >= MIN_BULLET_ROWS
        if "plan_fact" in blocks and not bullet_instead:
            pairs = pf_pairs
            # С порогами над полосой встаёт бейдж «план выполнен» и рамка — при
            # прежней высоте карточка включала прокрутку (замерено: не хватало
            # 18px). Ряд считается по номеру строки, поэтому высота у всей
            # пачки одна.
            pf_h = 6 if alerts else 5
            for i, (plan, fact) in enumerate(pairs):
                specs.append({"page": PAGE_OVERVIEW,
                              "name": f"{_split_name(fact['name'])['subject']}: план и факт",
                              "widget_type": "plan_fact",
                              # Полоса и без порогов показывает процент, но
                              # «187 %» и «64 %» выглядят одинаково спокойно.
                              # Порог красит недобор — его видно, не читая цифр.
                              "config": {"dataset_code": code,
                                         "plan_field": plan["code"], "fact_field": fact["code"],
                                         **({"alerts": [dict(r) for r in PLAN_PCT_ALERTS]}
                                            if alerts else {})},
                              "position_x": (i % 2) * 6, "position_y": ov_y + (i // 2) * pf_h,
                              "width": 6, "height": pf_h})
            if pairs:
                # По 2 в ряд: пара «план-факт» шире карточки (в ней два числа,
                # разница и полоса), а 2×6 заполняют 12 колонок ровно — иначе
                # карточки затекали бы в остаток ряда сбоку от полос.
                ov_y += ((len(pairs) + 1) // 2) * pf_h

        cards = [f for f in shown if view_of(f) in ("kpi", "both")] if "kpi" in blocks else []
        # Процентная ГРАФА формы («Доля отказов, %») — тоже спидометр, как и
        # расчётный процент: доля читается на шкале, а не голым числом. Раньше
        # этого не делали, потому что карточка складывала проценты по строкам
        # и шкала показала бы бессмыслицу; теперь такие столбцы усредняются
        # (`_aggregate`), и шкале есть что показывать.
        gauges = [f for f in cards if is_share(f["name"])]
        cards = [f for f in cards if f not in gauges]
        for i, f in enumerate(gauges):
            specs.append({"page": PAGE_OVERVIEW, "name": f["name"], "widget_type": "gauge",
                          "config": {"dataset_code": code, "value_field": f["code"], "unit": "%"},
                          "position_x": (i % 3) * 4, "position_y": ov_y + (i // 3) * 7,
                          "width": 4, "height": 7})
        if gauges:
            ov_y += _rows_height(len(gauges), 3, 7)
        # По ТРИ в ряд, а не по четыре: имена госформ длинные («Количество
        # отправленных уведомлений … · Факт · нарастающим итогом»), и на
        # четверти ширины от них оставалось «Количестı отправ…» — карточка
        # переставала отвечать на вопрос, что за число она показывает.
        # Высота 4 вместо 3: под числом помещается прирост к прошлому отчёту.
        # Разрезы одного показателя — ОДНОЙ карточкой. В госформе у показателя
        # обычно три столбца («нарастающим итогом», «… текущий месяц», «за
        # отчётную неделю»), и раньше каждый занимал свою карточку: тринадцать
        # карточек «Обзора» оказывались четырьмя показателями, а экран — стеной
        # одинаковых заголовков, где имя весит больше самого числа.
        # Группируем тем же разбором имени, что и всё остальное в системе.
        all_cards = list(cards)    # до группировки — по ним строится «Сравнение»
        groups: list = []          # [(ключ показателя, [поля])]
        singles: list = []
        by_subject: dict = {}
        # 🔴 План в группу разрезов не кладём. Разрезы — это способы посмотреть
        # на ОДНУ и ту же величину («нарастающим итогом», «за неделю»), а план
        # это цель, другая сущность. Строкой рядом с фактами он читается как
        # ещё одно фактическое число: на форме МАХ группа «записавшихся»
        # открывалась строкой «(до 1 сентября 2026 г.) 41 971» над «нарастающим
        # итогом 275 694», и разницу между ними видно не было.
        plan_cards = [f for f in cards if _split_name(f["name"]).get("role") == "plan"]
        plan_codes = {f["code"] for f in plan_cards}
        for f in cards:
            if f["code"] in plan_codes:
                continue
            key = _subject_key(_split_name(f["name"])["subject"])
            by_subject.setdefault(key, []).append(f)
        for key, fs in by_subject.items():
            (groups if len(fs) > 1 else singles).append((key, fs))
        # План, у которого ЕСТЬ факт, на странице уже показан — полосой
        # «план-факт» или термометром, и третий показ той же цифры лишний.
        # А вот план БЕЗ факта не показал бы никто: он остаётся отдельной
        # карточкой, чтобы не пропасть из виду молча.
        paired = {pl["code"] for pl, _fa in pf_pairs}
        for f in plan_cards:
            if f["code"] not in paired:
                singles.append((_subject_key(_split_name(f["name"])["subject"]), [f]))

        gi = 0
        for _key, fs in groups:
            head = _clean(_split_name(fs[0]["name"])["subject"]) or fs[0]["name"]
            # Высота — по числу разрезов: строка занимает ~1 ряд сетки.
            g_h = max(KPI_H, 3 + len(fs))
            specs.append({"page": PAGE_OVERVIEW, "name": head, "widget_type": "kpi_group",
                          "config": {"dataset_code": code,
                                     "value_fields": [f["code"] for f in fs],
                                     **({"compare_prev": True} if has_dyn else {})},
                          "position_x": (gi % 3) * KPI_W, "position_y": ov_y + (gi // 3) * g_h,
                          "width": KPI_W, "height": g_h})
            gi += 1
        if groups:
            ov_y += ((len(groups) + 2) // 3) * max(KPI_H, 3 + max(len(fs) for _k, fs in groups))

        cards = [fs[0] for _k, fs in singles]
        for i, f in enumerate(cards):
            specs.append({"page": PAGE_OVERVIEW, "name": f["name"], "widget_type": "kpi",
                          "config": {"dataset_code": code, "value_field": f["code"],
                                     # Прирост к прошлому отчёту и мини-график движения
                                     # показываем, когда периодов больше одного: иначе
                                     # сравнивать не с чем и рисовать нечего.
                                     #
                                     # Оба ставятся ВМЕСТЕ намеренно и ничего не стоят
                                     # сверх: прирост и спарклайн берутся из ОДНОГО
                                     # обращения к ряду периодов (см. _widgetcalc:
                                     # `if compare_prev or spark` → один запрос).
                                     # Голое число не отвечает «много это или мало»,
                                     # прирост отвечает «лучше или хуже, чем в прошлый
                                     # раз», а линия — «это разовый скачок или движение».
                                     **({"compare_prev": True, "spark": True} if has_dyn else {})},
                          "position_x": (i % 3) * KPI_W, "position_y": ov_y + (i // 3) * KPI_H,
                          "width": KPI_W, "height": KPI_H})
        if cards:
            ov_y += ((len(cards) + 2) // 3) * KPI_H

        # Сравнение: десяток карточек даёт точные числа, но не даёт увидеть
        # соотношение. 8 рядов — замерено: при 6 график ужимается до полоски.
        # Сравнение строится по ВСЕМ показателям, а не по остатку после
        # группировки: соотношение величин — как раз то, чего карточки (хоть
        # одиночные, хоть сгруппированные) не показывают.
        if "compare" in blocks and len(all_cards) > 1:
            specs.append({"page": PAGE_OVERVIEW, "name": f"{form_title(dsname)}: сравнение показателей",
                          "widget_type": "compare",
                          "config": {"dataset_code": code, "value_fields": [f["code"] for f in all_cards]},
                          "position_x": 0, "position_y": ov_y, "width": 12,
                          "height": 8 if len(all_cards) > 4 else 6})
            ov_y += 8 if len(all_cards) > 4 else 6

        # ── Матрица «строка × дата» ──────────────────────────────────────────
        # Появляется только там, где отвечает на свой вопрос: строк в форме
        # больше одной И отчётов больше одного. У формы с единственной строкой
        # («Донецкая Народная Республика») матрица дословно повторяет
        # «Динамику», и место она занимала бы зря.
        many_rows = int(d.get("rows") or 0) > 1
        matrix_added = False
        if "matrix" in blocks and has_dyn:
            # Разрез выбирается по самим данным. Строк в форме несколько
            # (районы, отделения) — интереснее «кто как двигался»; строка одна
            # (сводная форма по субъекту) — матрица по строкам выродилась бы в
            # одну строку, и нужен обратный разрез: показатели × даты, то самое,
            # ради чего файлы сводят в Excel руками.
            if many_rows:
                base = next((f for f in shown if view_of(f) in ("dynamics", "both")), shown[0])
                spec_cfg = {"dataset_code": code, "value_field": base["code"],
                            "max_periods": MATRIX_PERIODS}
                spec_name = f"{_split_name(base['name'])['subject']}: по строкам и датам"
            else:
                spec_cfg = {"dataset_code": code, "by": "fields",
                            "value_fields": [f["code"] for f in shown[:MATRIX_FIELDS]],
                            "max_periods": MATRIX_PERIODS}
                spec_name = f"{dsname}: показатели по датам"
            # Высота по числу строк, которые матрица реально покажет: у формы
            # заказчика их тринадцать, и в стандартные 8 рядов помещаются две.
            m_h = matrix_height(len(spec_cfg.get("value_fields") or []))
            specs.append({"page": PAGE_DYNAMICS, "name": spec_name, "widget_type": "matrix",
                          "config": spec_cfg,
                          "position_x": 0, "position_y": dyn_y, "width": 12, "height": m_h})
            dyn_y += m_h
            matrix_added = True

        # ── Динамика: тренд по каждому показателю, которому он назначен ──
        # Матрица показывает движение ВСЕХ показателей по всем датам, поэтому
        # рядом с ней тринадцать почти одинаковых графиков — дублирование:
        # страница превращалась в ленту, на которой ничего не выделено. Когда
        # матрица поставлена, оставляем тренды только для главных показателей
        # (остальные добавляются кнопкой «💡 показатели не показаны»).
        limit = MAX_TRENDS_WITH_MATRIX if matrix_added else MAX_AUTO_DYNAMICS
        trends = ([f for f in shown if view_of(f) in ("dynamics", "both")][:limit]
                  if has_dyn and "dynamics" in blocks else [])
        for i, f in enumerate(trends):
            specs.append({"page": PAGE_DYNAMICS, "name": f"Динамика: {f['name']}",
                          "widget_type": "dynamics",
                          "config": {"dataset_code": code, "value_field": f["code"]},
                          "position_x": (i % 3) * 4, "position_y": dyn_y + (i // 3) * 6,
                          "width": 4, "height": 6})
        if trends:
            dyn_y += ((len(trends) + 2) // 3) * 6

        # ── Первичные данные: разрез по строкам и сама таблица ──
        if "bar" in blocks:
            specs.append({"page": PAGE_RAW, "name": f"{dsname}: {shown[0]['name']} по строкам",
                          "widget_type": "bar",
                          "config": {"dataset_code": code, "value_field": shown[0]["code"]},
                          "position_x": 0, "position_y": raw_y, "width": 12, "height": 6})
            raw_y += 6
        if "table" in blocks:
            specs.append({"page": PAGE_RAW, "name": f"{dsname}: таблица", "widget_type": "table",
                          "config": {"dataset_code": code},
                          "position_x": 0, "position_y": raw_y, "width": 12, "height": 6})
            raw_y += 6

        # ── Виды, подобранные по СМЫСЛУ данных ───────────────────────────────
        # Ставятся только там, где отвечают на вопрос, которого нет у карточек и
        # трендов: воронка — «где теряются», светофор — «где плохо», тепловая
        # карта — «где и когда просело», водопад — «за счёт чего вырос итог».
        # Правило, которому не хватило данных, МОЛЧИТ (см. by_meaning_specs).
        if "by_meaning" in blocks:
            dates = sorted(d.get("period_dates") or [])
            extra = by_meaning_specs(
                fields, rows=d.get("rows") or 0, periods=d["periods"],
                first_period=dates[0] if dates else "", last_period=dates[-1] if dates else "",
                values=d.get("sums"), volumes=d.get("volumes"))
            for e in extra:
                kind, fs = e["kind"], e["fields"]
                w, h = WIDGET_SIZE.get(kind, (6, 6))
                # Правило может задать высоту само — у полос она зависит от
                # числа пар, и константа из таблицы прятала бы часть строк во
                # внутреннюю прокрутку (та же беда, что была у матрицы).
                h = e.get("height") or h
                cfg = {"dataset_code": code}
                if e.get("config"):
                    cfg.update(e["config"])
                elif kind in ("funnel", "heatmap"):
                    cfg["value_fields"] = [f["code"] for f in fs]
                else:
                    cfg["value_field"] = fs[0]["code"]
                # Светофор, полосы и термометр без порогов светят одним цветом —
                # то же правило, что у полосы «план-факт»: норма известна (100 %
                # это сам план), ставим сразу.
                cfg = apply_default_alerts(kind, cfg)
                # Каждая страница ведёт свой курсор по вертикали — виджет
                # встаёт под уже разложенным, а не поверх него.
                page = BY_MEANING_PAGE[kind]
                if page == PAGE_OVERVIEW:
                    y, ov_y = ov_y, ov_y + h
                elif page == PAGE_DYNAMICS:
                    y, dyn_y = dyn_y, dyn_y + h
                else:
                    y, raw_y = raw_y, raw_y + h
                specs.append({"page": page, "name": BY_MEANING_TITLE[kind].format(
                                  name=_clean(_split_name(fs[0]["name"])["subject"]) or fs[0]["name"]),
                              "widget_type": kind, "config": cfg,
                              "position_x": 0, "position_y": y, "width": w, "height": h})

        # ── Страницы по отчётным периодам ────────────────────────────────────
        # Сводные страницы обновляются сами: виджет читает последний выпуск.
        # Страница периода — наоборот, СРЕЗ: у её виджетов закреплена дата, и
        # приход новой недели их не меняет. Оба режима нужны заказчику, и
        # разницу между ними человек должен понимать (о ней сказано на самой
        # странице и в мастере).
        for period in _selected_periods(sel, d):
            py = 0
            page = f"{PAGE_PERIOD_PREFIX} {_ru_date(period)}"
            for i, f in enumerate(shown[:MAX_AUTO_KPI]):
                specs.append({"page": page, "name": f["name"], "widget_type": "kpi",
                              "config": {"dataset_code": code, "value_field": f["code"],
                                         "period": period},
                              "position_x": (i % 4) * 3, "position_y": py + (i // 4) * 3,
                              "width": 3, "height": 3})
            py += ((len(shown[:MAX_AUTO_KPI]) + 3) // 4) * 3
            specs.append({"page": page, "name": f"{dsname}: таблица за {_ru_date(period)}",
                          "widget_type": "table",
                          "config": {"dataset_code": code, "period": period},
                          "position_x": 0, "position_y": py, "width": 12, "height": 6})
    if pin_period:
        # Закрепляем дату ОДНИМ местом в конце, а не в десятке мест, где
        # формируется config: иначе новый вид виджета однажды забудут закрепить,
        # и на «срезе за 22.07» появится карточка со свежими данными.
        # Имя виджета уже могло получить дату (страницы-срезы) — не дублируем.
        for sp in specs:
            sp["config"].setdefault("period", pin_period)
    return specs


def _ru_date(iso: str) -> str:
    """Отчётная дата в подписи страницы — по-русски: ДД.ММ.ГГГГ."""
    parts = str(iso).split("-")
    return ".".join(reversed(parts)) if len(parts) == 3 else str(iso)


def _selected_periods(sel: Optional[dict], dataset: dict) -> list:
    """Отчётные даты, для которых человек попросил отдельные страницы.

    Пусто по умолчанию: страницы по неделям создаются ТОЛЬКО по явному выбору.
    У заказчика 15 недель — молча собрать 15 страниц значило бы сделать
    дашборд, который невозможно открыть.
    """
    if not sel:
        return []
    wanted = sel.get("periods") or []
    known = set(dataset.get("period_dates") or [])
    return [p for p in wanted if p in known][:MAX_AUTO_PERIOD_PAGES]


async def auto_build_plan(conn, org_id, object_id: str, selection: Optional[dict] = None,
                          alerts: bool = True, document_id: Optional[str] = None,
                          lock_period: bool = True) -> dict:
    """Предпросмотр мастера: что нашли в объекте и что будет создано."""
    obj = await conn.fetchrow(
        "select id, name from objects where id=$1::uuid and organization_id=$2", object_id, org_id)
    if obj is None:
        raise DashboardError("Объект не найден")
    doc = await document_release_info(conn, org_id, document_id) if document_id else None
    datasets = await collect_object_datasets(conn, org_id, object_id,
                                             only_code=doc["code"] if doc else None)
    if not datasets:
        raise DashboardError("У объекта нет выпущенных датасетов — сначала распознайте документ")

    warnings = []
    if len(datasets) > 1:
        warnings.append(
            "В объекте несколько наборов данных: "
            + ", ".join(f"«{d['code']}»" for d in datasets)
            + ". Обычно у объекта один набор, а разные коды появляются, когда выпуск "
              "сделали под новым именем — тогда недельные формы не складываются в один ряд.")
    trimmed = [d for d in datasets if len(d["fields"]) > MAX_AUTO_KPI]
    if trimmed:
        warnings.append(
            f"Показателей больше {MAX_AUTO_KPI} — на дашборд попадут первые {MAX_AUTO_KPI}, "
            "остальные видны в таблице.")

    specs = plan_auto_build(datasets, selection, alerts,
                            pin_period=(doc or {}).get("period") if lock_period else None)

    # Расчётные показатели («% выполнения плана», «доля доставленных»…): их
    # находит разбор имён столбцов — тот же, что в разделе «Метрики». Здесь они
    # нужны, чтобы человек мог поставить галочку прямо при сборке, а не заводить
    # метрику отдельно и потом руками добавлять по ней виджет.
    metrics = await _metric_options(conn, org_id, object_id)

    page_names = [PAGE_OVERVIEW, PAGE_DYNAMICS, PAGE_RAW] + sorted(
        {s["page"] for s in specs if str(s.get("page", "")).startswith(PAGE_PERIOD_PREFIX)})
    return {
        "object": {"id": str(obj["id"]), "name": obj["name"]},
        "metrics": metrics,
        "saved_selection": await _saved_selection(conn, object_id),
        "datasets": [{k: v for k, v in d.items()} for d in datasets],
        "blocks": BLOCKS,
        "warnings": warnings,
        "widgets": len(specs),
        "pages": [
            {"name": t, "widgets": sum(1 for s in specs if (s.get("page") or PAGE_OVERVIEW) == t)}
            for t in page_names
            if any((s.get("page") or PAGE_OVERVIEW) == t for s in specs)
        ],
        # Считаем по ФАКТИЧЕСКОМУ типу виджета, а не по названиям блоков: раньше
        # совпадали только те типы, чьё имя случайно совпало с именем блока, и в
        # сводке не было видно ни `kpi_group`, ни спидометров, ни видов «по
        # смыслу» — предпросмотр обещал меньше, чем создавал.
        "by_type": dict(sorted(
            Counter(s["widget_type"] for s in specs).items(), key=lambda kv: -kv[1])),
        # Как система предлагает показать каждый показатель — мастер выводит это
        # рядом с ним и даёт поменять.
        "views": {
            d["code"]: {f["code"]: default_view(f["name"], d["periods"] > 1) for f in d["fields"]}
            for d in datasets
        },
    }


async def _metric_options(conn, org_id, object_id: str) -> list:
    """Расчётные показатели, которые можно завести по данным этого объекта.

    Разбор имён столбцов живёт в `metrics/data_suggestions` и уже используется
    разделом «Метрики» — берём его же, чтобы система не предлагала в двух местах
    разное. Каждое предложение там проверено расчётом на реальных данных, то
    есть заведомо считается.

    Сбой не должен ронять мастер: без расчётных показателей он просто соберёт
    дашборд по сырым графам, как раньше.
    """
    try:
        from ..metrics.data_suggestions import suggest_from_data
        res = await suggest_from_data(conn, org_id, object_id=str(object_id))
    except Exception:  # noqa: BLE001 — подсказка не важнее самой сборки
        return []
    return [
        {"code": s["code"], "name": s["name"], "formula": s["formula"], "unit": s.get("unit"),
         "why": s.get("why"), "preview_value": s.get("preview_value"),
         "dataset_code": s.get("dataset_code"),
         # Вид предложения («plan_fact_pct», «percent_of», …) нужен, чтобы
         # выбрать виджет и решить, есть ли у показателя известная норма.
         "type": s.get("type")}
        for s in res.get("specs", [])
    ]


async def _saved_selection(conn, object_id: str) -> Optional[dict]:
    """Выбор прошлой сборки — им мастер открывается в следующий раз."""
    raw = await conn.fetchval("select build_preferences from objects where id=$1::uuid", object_id)
    if not raw:
        return None
    return json.loads(raw) if isinstance(raw, str) else raw


async def _remember_selection(conn, object_id: str, selection: Optional[dict],
                              metrics: Optional[list], alerts: bool = True) -> None:
    """Запомнить выбор: мастер не должен каждую неделю спрашивать одно и то же."""
    if selection is None and not metrics:
        return
    payload = {"selection": selection or {}, "metrics": list(metrics or []), "alerts": alerts}
    await conn.execute(
        "update objects set build_preferences=$2::jsonb where id=$1::uuid",
        object_id, json.dumps(payload, ensure_ascii=False, default=str))


async def _create_metric_widgets(conn, org_id, user_id, object_id: str, codes: list,
                                 page_id: str, start_y: int, alerts: bool = True) -> int:
    """Завести выбранные расчётные показатели и поставить по ним виджеты.

    Метрика создаётся ЧЕРНОВИКОМ и проходит обычный путь проверки; виджет при
    этом работает сразу, потому что берёт лучшую доступную версию формулы
    (одобренная → проверенная → черновик). Так человек видит число сразу, а
    порядок согласования не нарушается.

    Процентные показатели становятся спидометрами, остальные — карточками.
    Спидометры кладём отдельной пачкой ВЫШЕ карточек: шкале нужна карточка
    повыше, а разная высота в одном ряду наложилась бы.
    """
    if not codes:
        return 0
    from ..metrics import service as msvc
    from . import service as svc

    options = {m["code"]: m for m in await _metric_options(conn, org_id, object_id)}
    # Устаревшие предложения (метрику успели завести) молча пропускаем.
    picked = [options[c] for c in codes if c in options]
    gauges = [s for s in picked if _is_percent(s.get("unit"))]
    cards = [s for s in picked if not _is_percent(s.get("unit"))]

    async def place(specs: list, y: int, height: int) -> int:
        for spec, pos in _grid_rows(specs, y, per_row=3, width=4, height=height):
            try:
                metric = await msvc.create_metric(
                    conn, org_id, user_id, spec["code"], spec["name"], spec.get("why"), None)
                await msvc.create_version(
                    conn, org_id, user_id, str(metric["id"]), spec["formula"],
                    spec.get("unit"), None, "formula")
            except Exception:  # noqa: BLE001 — метрика с таким кодом уже есть
                pass
            wt, extra = metric_widget_spec(
                spec.get("unit"),
                plan_execution=alerts and spec.get("type") == "plan_fact_pct")
            await svc.create_widget(
                conn, org_id, user_id, page_id, spec["name"], wt,
                {"metric_code": spec["code"], "unit": spec.get("unit"), **extra}, pos)
        return y + _rows_height(len(specs), 3, height)

    # Спидометру нужна карточка выше: под шкалой идут бейдж порога и подпись.
    y = await place(gauges, start_y, 7)
    await place(cards, y, 5)
    return len(picked)


async def auto_build(conn, org_id, user_id, object_id: str, name=None,
                     selection: Optional[dict] = None, dashboard_id: Optional[str] = None,
                     metrics: Optional[list] = None, alerts: bool = True,
                     document_id: Optional[str] = None, lock_period: bool = True,
                     force: bool = False) -> dict:
    """Создаёт (или пересобирает) дашборд по объекту.

    `dashboard_id` — пересобрать существующий: страницы и виджеты заменяются,
    сам дашборд с его правами, комментариями и историей остаётся. Без него
    создаётся новый. Раньше каждое нажатие плодило новый дашборд.
    """
    obj = await conn.fetchrow(
        "select id, name from objects where id=$1::uuid and organization_id=$2", object_id, org_id)
    if obj is None:
        raise DashboardError("Объект не найден")
    doc = await document_release_info(conn, org_id, document_id) if document_id else None
    datasets = await collect_object_datasets(conn, org_id, object_id,
                                             only_code=doc["code"] if doc else None)
    if not datasets:
        raise DashboardError("У объекта нет выпущенных датасетов — сначала распознайте документ")
    specs = plan_auto_build(datasets, selection, alerts,
                            pin_period=(doc or {}).get("period") if lock_period else None)
    if not specs and not metrics:
        raise DashboardError("Нечего собирать — не выбрано ни одного показателя")

    from . import service as svc  # ленивый импорт: избегаем цикла модулей
    if dashboard_id:
        d = await conn.fetchrow(
            "select id, name from dashboards where id=$1::uuid and organization_id=$2",
            dashboard_id, org_id)
        if d is None:
            raise DashboardError("Дашборд не найден")
        did = str(d["id"])
        # Старое наполнение убираем: пересборка должна дать ровно то, что в плане,
        # а не смесь нового со старым. Сам дашборд не трогаем — на нём висят
        # права доступа, обсуждение и история версий.
        await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
        await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
    else:
        dash = await svc.create_dashboard(conn, org_id, user_id, name or f"Дашборд «{obj['name']}»",
                                          f"Авто-сборка по объекту «{obj['name']}»", None, force=force)
        did = str(dash["id"])
        # Папку проставляем сами: мастер и так знает объект, а раньше человек
        # шёл в дашборд и назначал её отдельным действием — иначе дашборд
        # висел «без папки» и не находился фильтром по банку отделов.
        folder_id = await conn.fetchval(
            "select d.folder_id from dataset_releases r "
            "join document_versions dv on dv.id = r.source_document_version_id "
            "join documents d on d.id = dv.document_id "
            "where r.object_id=$1::uuid and r.status <> 'superseded' and d.folder_id is not null "
            "group by d.folder_id order by count(*) desc limit 1", object_id)
        if folder_id:
            await conn.execute("update dashboards set folder_id=$2 where id=$1::uuid", did, folder_id)

    # Страницы создаём в осмысленном порядке и только те, на которых что-то есть:
    # пустая вкладка «Динамика» у формы с одним периодом сбивала бы с толку.
    pages: dict = {}
    first_pid = None
    # Дата, за которую закреплена страница-срез: у всех её виджетов один period.
    page_periods: dict = {}
    for spec in specs:
        title = spec.get("page") or PAGE_OVERVIEW
        per = spec.get("config", {}).get("period")
        if title not in page_periods:
            page_periods[title] = per
        elif page_periods[title] != per:
            page_periods[title] = None
    for spec in specs:
        title = spec.get("page") or PAGE_OVERVIEW
        if title not in pages:
            # Дата среза — на самой странице, а не только в имени: имя человек
            # может переименовать, и страница перестала бы опознаваться срезом.
            page = await svc.create_page(conn, org_id, user_id, did, title, None, AUTO_LAYOUT_MODE,
                                         page_periods.get(title))
            pages[title] = str(page["id"])
            if first_pid is None:
                first_pid = pages[title]
        await svc.create_widget(
            conn, org_id, user_id, pages[title], spec["name"], spec["widget_type"], spec["config"],
            {"position_x": spec["position_x"], "position_y": spec["position_y"],
             "width": spec["width"], "height": spec["height"]})

    # Расчётные показатели: заводим выбранные метрики и ставим по ним карточки
    # на «Обзор» — раньше принятие предложения создавало только черновик, а
    # виджет по нему человек добавлял руками и часто про это забывал.
    made_metrics = 0
    if metrics:
        if PAGE_OVERVIEW not in pages:
            page = await svc.create_page(conn, org_id, user_id, did, PAGE_OVERVIEW, None, AUTO_LAYOUT_MODE)
            pages[PAGE_OVERVIEW] = str(page["id"])
            if first_pid is None:
                first_pid = pages[PAGE_OVERVIEW]
        # Ниже всего, что уже разложено на «Обзоре», — иначе карточки наложились бы.
        below = max(
            [s["position_y"] + s["height"] for s in specs
             if (s.get("page") or PAGE_OVERVIEW) == PAGE_OVERVIEW] or [0])
        made_metrics = await _create_metric_widgets(
            conn, org_id, user_id, object_id, metrics, pages[PAGE_OVERVIEW], below, alerts)

    await _remember_selection(conn, object_id, selection, metrics, alerts)
    return {"dashboard_id": did, "page_id": first_pid, "pages": len(pages),
            "widgets": len(specs) + made_metrics, "metrics": made_metrics}


async def place_metric_widget(conn, org_id, user_id, *, page_id: str, metric_code: str,
                              name: str, unit: Optional[str] = None,
                              based_on: Optional[List[str]] = None,
                              dataset_code: Optional[str] = None) -> dict:
    """Поставить карточку показателя РЯДОМ с близким по смыслу виджетом.

    Новый виджет, добавленный «в конец страницы», уезжает вниз и теряется:
    руководитель смотрит на «Обзор» и не видит, что доля посчитана рядом с тем
    показателем, от которого она берётся. Поэтому ищем виджет, который уже
    показывает поля, лежащие в основе формулы, и встаём вплотную к нему —
    справа, если в ряду есть место, иначе следующей строкой под ним.

    Место выбирает система, но последнее слово за человеком: виджеты можно
    двигать мышью, и перестановка ничего не ломает.
    """
    from . import service as svc

    # Формулу разбираем всегда: из неё видно и на каких полях стоит показатель
    # (по ним ищется соседний виджет), и считает ли он выполнение плана — то
    # есть можно ли ему проставить пороги «нормы».
    derived = await _metric_fields(conn, org_id, metric_code)
    fields = set(based_on or [])
    if not fields:
        fields = set(derived["fields"])
        dataset_code = dataset_code or (derived["datasets"][0] if derived["datasets"] else None)
    rows = await conn.fetch(
        "select id, config, position_x, position_y, width, height "
        "from widgets where page_id=$1::uuid order by position_y, position_x", page_id)

    best: Optional[dict] = None
    best_score = 0.0
    for r in rows:
        cfg = _cfg(r)
        used = {cfg.get(k) for k in ("value_field", "plan_field", "fact_field") if cfg.get(k)}
        used |= set(cfg.get("value_fields") or [])
        hit = len(used & fields)
        # Родство считаем ДОЛЕЙ совпадения, а не числом совпавших полей.
        # Иначе общий график «Сравнение показателей», перечисляющий все графы
        # формы, всегда выигрывал у карточки нужного показателя — и новая
        # карточка уезжала под него в самый низ страницы, вместо того чтобы
        # встать рядом с показателем, от которого она считается.
        score = (hit / len(used)) if used and hit else 0.0
        # Тот же датасет — слабое родство: лучше, чем ничего, но заведомо
        # уступает совпадению по конкретным показателям.
        if not score and dataset_code and cfg.get("dataset_code") == dataset_code:
            score = 0.1
        if score > best_score:
            best, best_score = r, score

    # Процент читается на шкале, а не голым числом; спидометру нужна карточка
    # повыше. Пороги — только выполнению плана: у него норма известна.
    wt, extra = metric_widget_spec(unit, plan_execution="PLAN_FACT_PCT" in derived["funcs"])
    width, height = 4, (7 if wt == "gauge" else 5)

    def free(x: int, y: int) -> bool:
        """Свободна ли клетка: иначе сетка растолкает соседей при отрисовке."""
        if x + width > 12:
            return False
        for r in rows:
            rx, ry, rw, rh = r["position_x"], r["position_y"], r["width"], r["height"]
            if x < rx + rw and rx < x + width and y < ry + rh and ry < y + height:
                return False
        return True

    if best is None:
        # Родственника нет — в конец страницы (сетка сама подожмёт вверх).
        pos = {"position_x": 0, "position_y": 999, "width": width, "height": height}
    else:
        bx, by, bw = best["position_x"], best["position_y"], best["width"]
        # Ищем ближайшее СВОБОДНОЕ место: сначала справа от родственника, затем
        # свободные клетки его ряда, затем строка под ним. Ставить в занятую
        # клетку нельзя — сетка при отрисовке сдвинет чужие карточки, и человек
        # увидит, что дашборд «поехал» сам по себе.
        spot = None
        # Сначала вплотную справа, затем свободные места ряда, затем ряды ниже —
        # чем дальше, тем хуже, поэтому спускаемся недалеко (4 ряда карточек).
        for dy in range(0, 4 * height, height):
            y = by + dy
            order = ([bx + bw] if dy == 0 else [bx]) + [c * 4 for c in range(3)]
            for x in order:
                if free(x, y):
                    spot = (x, y)
                    break
            if spot:
                break
        if spot:
            pos = {"position_x": spot[0], "position_y": spot[1], "width": width, "height": height}
        else:
            # Свободного места поблизости нет: ставим ВПЛОТНУЮ справа от
            # родственника и позволяем сетке подвинуть остальных. Соседство
            # важнее неподвижности: карточка, уехавшая в конец страницы, теряет
            # весь смысл «рядом с показателем, из которого считается».
            pos = {"position_x": min(bx + bw, 8), "position_y": by,
                   "width": width, "height": height}

    cfg = {"metric_code": metric_code, **extra}
    if unit:
        cfg["unit"] = unit
    w = await svc.create_widget(conn, org_id, user_id, page_id, name, wt, cfg, pos)
    return {"widget_id": w["id"], "placed_near": str(best["id"]) if best is not None else None,
            "position": pos}


async def _metric_fields(conn, org_id, metric_code: str) -> dict:
    """Поля, датасеты и функции, из которых собрана формула показателя.

    Берём лучшую версию (одобренная → проверенная → черновик) — ту же, по
    которой виджет и будет считать. Разбираем разобранный AST, а не текст:
    в тексте те же ссылки пришлось бы искать регулярками.
    """
    ast = await conn.fetchval(
        "select mv.formula_ast from metric_versions mv join metrics m on m.id = mv.metric_id "
        "where m.organization_id=$1 and m.code=$2 "
        "order by case mv.status when 'approved' then 0 when 'validated' then 1 "
        "                        when 'draft' then 2 else 3 end, mv.version_no desc limit 1",
        org_id, metric_code)
    if not ast:
        return {"fields": [], "datasets": [], "funcs": []}
    if isinstance(ast, str):
        ast = json.loads(ast)

    fields: List[str] = []
    datasets: List[str] = []
    funcs: List[str] = []

    def walk(node) -> None:
        if not isinstance(node, dict):
            return
        # Имя функции («PLAN_FACT_PCT», «PERCENT_OF») говорит о СМЫСЛЕ
        # показателя: по нему видно, есть ли у него известная норма.
        if node.get("fn"):
            funcs.append(str(node["fn"]))
        elif node.get("t") == "percent_of":
            funcs.append("PERCENT_OF")
        if node.get("t") in ("field", "cell"):
            if node.get("field") and node["field"] not in fields:
                fields.append(node["field"])
            if node.get("col") and node["col"] not in fields:
                fields.append(node["col"])
            if node.get("dataset") and node["dataset"] not in datasets:
                datasets.append(node["dataset"])
        for val in node.values():
            if isinstance(val, dict):
                walk(val)
            elif isinstance(val, list):
                for it in val:
                    walk(it)

    walk(ast)
    return {"fields": fields, "datasets": datasets, "funcs": funcs}


async def dashboard_metric_codes(conn, dashboard_id: str) -> list:
    """Коды показателей, уже показанных на дашборде: не предлагаем их дважды."""
    rows = await conn.fetch(
        "select config from widgets where dashboard_id=$1::uuid", dashboard_id)
    out: set = set()
    for r in rows:
        cfg = _cfg(r)
        for key in ("metric_code", "plan_metric", "fact_metric"):
            if cfg.get(key):
                out.add(cfg[key])
    return sorted(out)
