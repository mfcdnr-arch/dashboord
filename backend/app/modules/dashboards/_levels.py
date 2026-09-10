"""Лестница уровней: фильтр по графам и расчёт одной ступени.

Кусок 3 «лестницы». Куски 1–2 научили систему видеть ступени в именах граф и
хранить подтверждённую человеком иерархию; здесь по ней начинают ходить.

🔴 Почему это отдельный механизм, а не приспособленный существующий. Drill-down
в системе есть с 22.08, но он работает ПО СТРОКАМ (`row=`): человек кликает по
строке таблицы, и вся страница показывает данные этой строки. Лестница же идёт
ПО ГРАФАМ — «Росреестр» и «Государственная регистрация прав» это не строки
формы, а сегменты имени графы, — и такого фильтра в системе не было вовсе.
Строки остаются самой НИЖНЕЙ ступенью: пройдя все уровни граф, лестница
упирается в отделения, и дальше работает уже существующий фильтр строк.

Устройство фильтра намеренно повторяет то, как 17.08 задним числом
приделывался фильтр периода: он живёт в ОДНОЙ обёртке над расчётом виджета и
сужает конфигурацию до того, как виджет её увидит. Поэтому ни один из 26 типов
виджетов не пришлось трогать по отдельности — а значит и забыть про новый тип
при следующей правке нельзя.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from ..ingestion.hierarchy import pick_separator, split_segments
from ._aggregate import aggregate_series, is_total_column


def path_of(name: Optional[str], sep: str) -> List[str]:
    """Ступени, к которым относится графа: все сегменты имени, кроме последнего.

    Последний сегмент — мера («Принято, ед.»), она не ступень. Имя без
    разделителя ступеней не имеет вовсе.
    """
    segs = split_segments(name, sep)
    return segs[:-1] if len(segs) >= 2 else []


def measure_of_name(name: Optional[str], sep: str) -> str:
    """Что графа измеряет — последний сегмент имени."""
    segs = split_segments(name, sep)
    return segs[-1] if len(segs) >= 2 else ""


def under(name: Optional[str], sep: str, path: Sequence[str]) -> bool:
    """Лежит ли графа в этой ветке лестницы.

    Пустой путь — корень, под ним лежит всё. Ветка сравнивается ПОЛНЫМИ
    сегментами, а не началом строки: иначе «Минюст» поймал бы «Минюстиции», а
    ветка «СФР» — любую графу, чьё имя с него начинается.
    """
    if not path:
        return True
    own = path_of(name, sep)
    if len(own) < len(path):
        return False
    return all(own[i] == p for i, p in enumerate(path))


# 🔴 Виды, читающие ВСЕ графы формы. Списка граф в их конфигурации нет вовсе,
# поэтому общее правило («оставить от списка графы ветки») их не задевало, и
# внутри «Росреестра» такой виджет молча показывал форму целиком. Замер на
# дашборде заказчика: таблица отдавала 327 колонок и в корне, и в ветке — то
# есть данные не из той ветки под видом её собственных, ровно та ошибка, ради
# которой фильтр и заводился. Ветку им надо назвать явно.
WHOLE_FORM_TYPES = {"table", "field_list"}


def narrow_cfg(cfg: dict, titles: Dict[str, str], sep: str,
               path: Sequence[str], widget_type: Optional[str] = None) -> Optional[dict]:
    """Сузить конфигурацию виджета до ветки лестницы.

    Возвращает `None`, если в ветке не осталось ни одной графы виджета: это не
    ошибка, а честный ответ «по этой ветке виджету показывать нечего» — его и
    покажет карточка вместо цифры не из той ветки.

    🔴 Свод («ИТОГО · Принято, ед.») из ветки исключается. Он содержит в себе
    все остальные графы формы, и внутри ветки «Росреестр» его значение — это
    итог по ВСЕЙ форме: оставь мы его, карточка ветки показала бы 5 426 там,
    где правда 826, причём выглядело бы это совершенно правдоподобно.
    """
    if not path:
        return cfg

    def keep(code: Optional[str]) -> bool:
        if not code:
            return False
        name = titles.get(code, code)
        return under(name, sep, path) and not is_total_column(name)

    # Вид читает всю форму и своего списка граф не имеет — составляем его по
    # ветке. Пустая ветка означает, что показывать нечего: тот же честный ответ,
    # что и у виджета, у которого графа из ветки выпала.
    if widget_type in WHOLE_FORM_TYPES and cfg.get("value_fields") is None and not cfg.get("value_field"):
        branch = [c for c in titles if keep(c)]
        if not branch:
            return None
        return {**cfg, "value_fields": branch}

    out = dict(cfg)
    fields = [c for c in (cfg.get("value_fields") or []) if keep(c)]
    single = cfg.get("value_field")

    # Набор граф сузился до пустого — виджету в этой ветке нечего показывать.
    if (cfg.get("value_fields") or single) and not fields and not keep(single):
        return None

    if cfg.get("value_fields") is not None:
        out["value_fields"] = fields
    if single is not None:
        # У виджета с ОДНОЙ графой замены нет: либо она в ветке, либо виджет
        # молчит. Подставлять «похожую» графу из ветки нельзя — это была бы
        # уже другая цифра под тем же названием.
        out["value_field"] = single if keep(single) else (fields[0] if fields else None)
        if out["value_field"] is None:
            return None
    # План и факт — пара; если из ветки выпала половина, сравнивать нечего.
    for key in ("plan_field", "fact_field"):
        if cfg.get(key) is not None and not keep(cfg[key]):
            return None
    return out


def children_of(names: Sequence[str], sep: str, path: Sequence[str],
                depth: int) -> List[str]:
    """Значения СЛЕДУЮЩЕЙ ступени внутри ветки, в порядке появления."""
    out: List[str] = []
    for n in names:
        if not under(n, sep, path) or is_total_column(n):
            continue
        own = path_of(n, sep)
        if len(own) <= depth:
            continue
        if own[depth] not in out:
            out.append(own[depth])
    return out


def step_rows(values: Sequence[dict], sep: str, path: Sequence[str], depth: int,
              measure: Optional[str]) -> List[dict]:
    """Одна ступень лестницы: дети ветки со своими числами.

    `values` — строки вида {name, row_label, value}. Сворачиваем той же
    `aggregate_series`, что и карточка показателя: количества складываются,
    доли усредняются. Иначе ступень лестницы и карточка на той же странице
    показали бы по одному показателю разные числа.
    """
    buckets: Dict[str, List[float]] = {}
    for v in values:
        name = v.get("name") or ""
        if not under(name, sep, path) or is_total_column(name):
            continue
        if measure and measure_of_name(name, sep) != measure:
            continue
        own = path_of(name, sep)
        if len(own) <= depth:
            continue
        buckets.setdefault(own[depth], []).append(float(v.get("value") or 0))

    out: List[dict] = []
    for key, nums in buckets.items():
        total, how = aggregate_series(nums, measure or key)
        out.append({"value": key, "total": total, "aggregate": how})
    out.sort(key=lambda r: -abs(r["total"]))
    return out


def leaf_rows(values: Sequence[dict], sep: str, path: Sequence[str],
              measure: Optional[str], allowed: Optional[set] = None) -> List[dict]:
    """Нижняя ступень: строки формы (отделения) внутри ветки.

    Разрешённые строки применяются здесь же: лестница не должна становиться
    обходным путём к строкам, которых человеку видеть нельзя.
    """
    buckets: Dict[str, List[float]] = {}
    for v in values:
        name = v.get("name") or ""
        label = v.get("row_label") or ""
        if allowed is not None and label not in allowed:
            continue
        if not under(name, sep, path) or is_total_column(name):
            continue
        if measure and measure_of_name(name, sep) != measure:
            continue
        buckets.setdefault(label, []).append(float(v.get("value") or 0))

    out: List[dict] = []
    for key, nums in buckets.items():
        total, how = aggregate_series(nums, measure or key)
        out.append({"value": key, "total": total, "aggregate": how})
    out.sort(key=lambda r: -abs(r["total"]))
    return out


# ── Ступень лестницы для страницы дашборда ──────────────────────────────────

async def page_ladder(conn, org_id, page_id: str, user: dict,
                      path: Optional[Sequence[str]] = None,
                      measure: Optional[str] = None,
                      from_date=None, to_date=None) -> Dict:
    """Одна ступень лестницы: где мы находимся и что показать ниже.

    Датасет берётся ТОТ ЖЕ, что у виджетов страницы (`_rowrank._collect`), —
    иначе лестница ходила бы по одной форме, а страница показывала другую.
    Иерархия — подтверждённая человеком: неподтверждённую не применяем вовсе
    (решение заказчика «не угадывать молча»), устаревшую тоже.
    """
    from ..objects.levels import load_confirmed
    from . import service  # ленивый импорт: service тянет этот модуль
    from ._rowrank import _collect
    from ._rowrls import allowed_rows_for_dataset
    from ._widgetcalc import _period_for_range
    from ._widgetsources import _field_titles

    path = [p for p in (path or []) if str(p).strip()]
    wl = await service.list_page_widgets(conn, org_id, page_id, user)
    code, _fields, period = _collect(wl["widgets"])
    if not code:
        return {"available": False, "reason": "На странице нет виджетов по данным формы — "
                                              "разбирать по ступеням нечего."}

    obj_id = await conn.fetchval(
        "select object_id from dataset_releases where organization_id=$1 and code=$2 "
        "and status<>'superseded' order by reporting_period_start desc nulls last limit 1",
        org_id, code)
    conf = await load_confirmed(conn, obj_id) if obj_id else None
    if not conf:
        return {"available": False, "dataset_code": code,
                "reason": "Ступени этой формы ещё не подтверждены. Откройте объект и "
                          "подтвердите их в блоке «Ступени формы»."}

    if period is None and (from_date or to_date):
        period = await _period_for_range(conn, org_id, code, from_date, to_date)
    titles = await _field_titles(conn, org_id, code, period)
    sep = pick_separator(list(titles.values())) or " · "

    names = [conf_lv.get("name") or f"Ступень {i + 1}"
             for i, conf_lv in enumerate(conf.get("levels") or [])]
    row_level = conf.get("row_level") or "Строка"
    depth = len(path)
    measure = measure or conf.get("measure_default")

    values = await _values(conn, org_id, code, period)
    allowed = await allowed_rows_for_dataset(conn, org_id, user, code)

    # 🔴 Мера — то, что можно измерить, поэтому список собираем по графам, в
    # которых есть ЧИСЛА, а не по всем именам подряд. Иначе в переключатель
    # попадают текстовые графы: на форме РЦО это «Наименование отдела МФЦ» —
    # выбрать его можно, а показать по нему нечего.
    measures = sorted({m for m in (measure_of_name(v.get("name"), sep) for v in values) if m})
    out: Dict = {
        "available": True, "dataset_code": code, "separator": sep,
        "levels": names, "row_level": row_level, "path": list(path),
        "measure": measure, "measures": measures,
        "as_of": str(period) if period else None,
    }

    # Прошли все ступени граф — ниже только строки формы (отделения).
    if depth >= len(names):
        out.update({"level_name": row_level, "is_rows": True,
                    "children": leaf_rows(values, sep, path, measure, allowed)})
        return out

    kids = step_rows(values, sep, path, depth, measure)
    if not kids:
        # 🔴 Ступень пропущена — и об этом говорим словами. У ЕСИА, ЗАГС и ОМС
        # ступени «Услуга» в форме нет (одна графа на всё ведомство), но
        # отделения есть. Молчаливый пропуск читался бы как «здесь показаны
        # услуги», то есть человек принял бы отделения за услуги.
        #
        # Имя уровня подставляется ТОЛЬКО через слово «уровню»: имя задаёт
        # человек, и склонять его нельзя.
        out.update({
            "level_name": row_level, "is_rows": True, "skipped_level": names[depth],
            # 🔴 Имена уровней задаёт человек, и склонять их нельзя: «сразу
            # отделение» для уровня «Отделение» ещё читается, а для «МФЦ» или
            # «Вид услуги» вышла бы неграмотность. Падеж берут на себя слова
            # «по уровню» и «уровень», сами имена стоят в кавычках как есть.
            "note": f"Источник не даёт разбивки по уровню «{names[depth]}» — "
                    f"ниже сразу уровень «{row_level}». "
                    "Это устройство формы, а не пропуск в данных.",
            "children": leaf_rows(values, sep, path, measure, allowed)})
        return out

    out.update({"level_name": names[depth], "is_rows": False, "children": kids})
    return out


async def _values(conn, org_id, dataset_code: str, period=None) -> List[dict]:
    """Значения активного выпуска с именами граф — сырьё для ступени."""
    from ..metrics import resolver as mr
    rel = await mr._active_release(conn, org_id, dataset_code, period)
    if rel is None:
        return []
    rows = await conn.fetch(
        "select coalesce(cf.name, v.canonical_field_code) as name, v.row_label, "
        "v.value_number as value from dataset_values v "
        "left join canonical_fields cf on cf.code = v.canonical_field_code "
        "  and cf.object_id = (select object_id from dataset_releases where id=$1) "
        "where v.dataset_release_id = $1 and v.value_number is not null", rel)
    return [dict(r) for r in rows]


# ── Страница, собранная ПОД лестницу ────────────────────────────────────────

LADDER_PAGE = "Разбор по ступеням"


async def _ladder_context(conn, org_id, dashboard_id: str) -> Dict:
    """Форма дашборда, её объект и подтверждённая иерархия — общее для обоих шагов.

    Предпросмотр и сборка обязаны смотреть на одно и то же: иначе обещанный
    состав однажды разошёлся бы с созданным (то же правило, по которому мастер
    авто-сборки считает план и результат ОДНОЙ функцией).
    """
    from ..ingestion.hierarchy import pick_separator
    from ..objects.levels import load_confirmed
    from ._base import DashboardError
    from ._widgetsources import _field_titles

    code = await conn.fetchval(
        "select config->>'dataset_code' as code from widgets "
        "where dashboard_id=$1::uuid and config->>'dataset_code' is not null "
        "group by 1 order by count(*) desc limit 1", dashboard_id)
    if not code:
        raise DashboardError("На дашборде нет виджетов по данным формы — "
                             "разбирать по ступеням нечего.")
    obj_id = await conn.fetchval(
        "select object_id from dataset_releases where organization_id=$1 and code=$2 "
        "and status<>'superseded' order by reporting_period_start desc nulls last limit 1",
        org_id, code)
    conf = await load_confirmed(conn, obj_id) if obj_id else None
    if not conf:
        raise DashboardError("Ступени этой формы ещё не подтверждены. Откройте объект и "
                             "подтвердите их в блоке «Ступени формы».")
    titles = await _field_titles(conn, org_id, code)
    sep = pick_separator(list(titles.values())) or " · "
    levels = [lv.get("name") or f"Ступень {i + 1}"
              for i, lv in enumerate(conf.get("levels") or [])]
    measure = conf.get("measure_default") or ""
    if not measure:
        # Меру можно не подтвердить — тогда берём самую частую в форме: это
        # догадка о ПОКАЗЕ, а не о данных, и человек меняет её переключателем.
        counts: Dict[str, int] = {}
        for nm in titles.values():
            m = measure_of_name(nm, sep)
            if m:
                counts[m] = counts.get(m, 0) + 1
        measure = max(counts, key=lambda k: counts[k]) if counts else ""
    return {"dataset_code": code, "object_id": str(obj_id), "separator": sep,
            "levels": levels, "row_level": conf.get("row_level") or "Строка",
            "measure": measure}


def ladder_page_specs(ctx: Dict) -> List[dict]:
    """Виджеты страницы лестницы.

    🔴 Главное правило страницы: КАЖДЫЙ её виджет обязан пережить спуск. На
    обычной странице большинство виджетов настроено на одну графу («ИТОГО ·
    Выдано, ед.»), а свод из ветки исключается — замер на дашборде заказчика:
    внутри «Росреестра» из 12 виджетов «Обзора» считались 2, остальные честно
    молчали. Здесь виджеты описаны так, что ветка их только сужает:

      • рейтинг — по МЕРЕ, а не по графе: «Принято, ед.» разворачивается в
        графы ветки и сворачивается по строке;
      • «Показатели списком» и таблица списка граф не имеют вовсе, и ветку им
        называет фильтр лестницы.

    Новых типов виджетов не заводим — это решение из плана: страница рисуется
    тем, что уже есть.
    """
    from ._suggest import WIDGET_SIZE

    code, measure = ctx["dataset_code"], ctx["measure"]
    row_level = ctx["row_level"]
    specs: List[dict] = []
    y = 0

    def add(kind: str, name: str, cfg: dict, height: Optional[int] = None):
        nonlocal y
        w, h = WIDGET_SIZE[kind]
        specs.append({"page": LADDER_PAGE, "name": name, "widget_type": kind, "config": cfg,
                      "position_x": 0, "position_y": y, "width": 12, "height": height or h})
        y += (height or h)

    meas = f" · {measure}" if measure else ""
    add("ranked", f"{row_level}: кто впереди и кто в хвосте{meas}",
        {"dataset_code": code, "measure": measure, "top_n": 5, "bottom": True})
    add("field_list", "Из чего складывается ветка",
        {"dataset_code": code, "sort": "value", "hide_zero": True, "group_sep": ctx["separator"]})
    # Имя без меры: таблица показывает ВСЕ графы ветки, а не одну меру, — и
    # подписать её мерой значило бы соврать о содержимом.
    add("table", "Первичные строки ветки", {"dataset_code": code})
    return specs


async def plan_ladder_page(conn, org_id, dashboard_id: str) -> Dict:
    """Что будет создано — до того, как создавать."""
    ctx = await _ladder_context(conn, org_id, dashboard_id)
    specs = ladder_page_specs(ctx)
    exists = await conn.fetchval(
        "select id from dashboard_pages where dashboard_id=$1::uuid and name=$2",
        dashboard_id, LADDER_PAGE)
    return {"page": LADDER_PAGE, "exists": bool(exists), "dataset_code": ctx["dataset_code"],
            "levels": ctx["levels"], "row_level": ctx["row_level"], "measure": ctx["measure"],
            "widgets": [{"name": s["name"], "widget_type": s["widget_type"]} for s in specs]}


async def build_ladder_page(conn, org_id, user_id, dashboard_id: str) -> Dict:
    """Добавить страницу лестницы к СУЩЕСТВУЮЩЕМУ дашборду.

    Отдельной страницей, а не пересборкой: у заказчика дашборд собран и правлен
    руками, и заменять его наполнение ради лестницы нельзя (решение «к уже
    загруженным формам — по кнопке»). Повторное нажатие заменяет наполнение
    ТОЛЬКО этой страницы — иначе кнопка плодила бы одинаковые страницы.
    """
    from . import service as svc
    from ._suggest import AUTO_LAYOUT_MODE

    ctx = await _ladder_context(conn, org_id, dashboard_id)
    specs = ladder_page_specs(ctx)
    pid = await conn.fetchval(
        "select id from dashboard_pages where dashboard_id=$1::uuid and name=$2",
        dashboard_id, LADDER_PAGE)
    if pid:
        await conn.execute("delete from widgets where page_id=$1::uuid", str(pid))
        pid = str(pid)
    else:
        page = await svc.create_page(conn, org_id, user_id, dashboard_id, LADDER_PAGE,
                                     None, AUTO_LAYOUT_MODE)
        pid = str(page["id"])
    for s in specs:
        await svc.create_widget(conn, org_id, user_id, pid, s["name"], s["widget_type"], s["config"],
                                {"position_x": s["position_x"], "position_y": s["position_y"],
                                 "width": s["width"], "height": s["height"]})
    return {"page_id": pid, "page": LADDER_PAGE, "widgets": len(specs)}
