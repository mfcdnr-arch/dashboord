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


def narrow_cfg(cfg: dict, titles: Dict[str, str], sep: str,
               path: Sequence[str]) -> Optional[dict]:
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
