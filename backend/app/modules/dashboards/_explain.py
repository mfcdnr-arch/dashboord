"""Что за цифра в виджете — пояснение для значка ⓘ и для предложения виджетов.

Раньше ⓘ объяснял ТИП виджета («карточка показывает одно число»), то есть то,
что и так видно. Человек, глядя на «929 825», спрашивает другое: что это за
число, откуда взято и можно ли ему верить.

С 24.09.2026 пояснение устроено ЧАСТЯМИ — так его показывает предложение
виджетов (решение заказчика 23.09: «текст из предложения остаётся у созданного
виджета в ⓘ, и пользователь дашборда видит то же, что видел модератор при
выборе»):

  what    — что показывает виджет (первая фраза);
  answers — на какой вопрос отвечает;
  data    — из каких граф какой формы строится;
  how     — как считается (свёртка строк, месяцы, приросты);
  caveats — что учесть (обрезка, пороги, закреплённая дата).

И предложение, и ⓘ берут части из ОДНОЙ функции `widget_sections`: заведи
предложение свой текст — он однажды разошёлся бы с подсказкой.

Собирается пачкой на всю страницу (несколько запросов на список виджетов, а не
по запросу на каждый): подсказка нужна сразу при наведении.

Ничего не выдумываем: если описание не задано, так и говорим. Придуманное
пояснение к государственному показателю хуже отсутствующего.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..metrics.versions import best_version_order
from ._aggregate import is_share
from ._alerts import _cfg

# Действующая версия формулы: правило одно на систему (metrics/versions.py).
# Своя копия `order by` здесь однажды разошлась бы с подсказкой ⓘ и с разбором
# «из чего складывается» — так и было до 21.09.2026.
_BEST_VER = best_version_order()

# Подсказка — не статья, но с 24.09 в ней те же части, что в предложении
# виджетов, и прежних 400 знаков на них не хватало (обрезалось «Учтите» —
# самое нужное). Полный разбор по-прежнему доступен по «🔍 подробнее».
MAX_EXPLAIN = 700

# Порядок частей в тексте ⓘ: сначала что это, потом зачем, откуда, как, что учесть.
SECTION_ORDER = ("what", "answers", "data", "how", "caveats")
_SECTION_PREFIX = {"answers": "Отвечает: ", "caveats": "Учтите: "}

# Русские названия видов — для чипа в предложении виджетов. Те же слова, что в
# галерее виджетов фронта (`WidgetPicker.WIDGET_GROUPS`); согласие держит
# test_explain_sections::test_type_labels_match_the_gallery.
WIDGET_TYPE_RU = {
    "kpi": "KPI (число)", "kpi_group": "Показатель в разрезах", "gauge": "Спидометр",
    "plan_fact": "План-факт", "bullet": "Полосы план-факт", "thermometer": "Термометр к сроку",
    "bar": "Столбцы", "line": "Линия", "pie": "Круговая", "dynamics": "Динамика",
    "yoy": "Год к году", "compare": "Сравнение", "waterfall": "Водопад", "funnel": "Воронка",
    "objects_compare": "Сравнение подразделений", "cross_dataset_compare": "Сравнение источников",
    "table": "Таблица", "heatmap": "Тепловая карта", "pivot": "Сводная таблица",
    "matrix": "Матрица по датам", "spark_table": "Строки с мини-графиками",
    "field_list": "Показатели списком", "status_grid": "Светофор", "ranked": "Рейтинг строк",
    "text": "Текст/заголовок", "image": "Картинка/лого",
}

_STATUS_RU = {
    "approved": "формула одобрена",
    "validated": "формула проверена, ждёт одобрения",
    "draft": "формула в черновике — значение предварительное",
    # Про снятую с эксплуатации молчать нельзя ровно по той же причине, что
    # и про черновик: на карточке её значение выглядит как утверждённое.
    "deprecated": "формула снята с эксплуатации — действующей у показателя нет",
    "archived": "формула в архиве — действующей у показателя нет",
}

_MONTHS_GEN = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля",
               "августа", "сентября", "октября", "ноября", "декабря")


def _clip(text: str, limit: int = MAX_EXPLAIN) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _ru_day(iso: Optional[str]) -> str:
    """Дата словами: «1 сентября 2026 г.». ISO в подсказке читается как код."""
    parts = str(iso or "").split("-")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return str(iso or "")
    y, m, d = (int(p) for p in parts)
    return f"{d} {_MONTHS_GEN[m - 1]} {y} г." if 1 <= m <= 12 else str(iso)


def sections_text(sections: Dict[str, str]) -> str:
    """Части пояснения → текст для ⓘ. Порядок один для всех видов."""
    out = []
    for key in SECTION_ORDER:
        body = (sections.get(key) or "").strip()
        if body:
            out.append(_SECTION_PREFIX.get(key, "") + body)
    return " ".join(out)


# --------------------------------------------------------------------------- #
# Справочники: метрики, графы и формы — пачкой на все виджеты
# --------------------------------------------------------------------------- #

def _field_codes(cfg: dict) -> List[str]:
    """Все коды граф, на которые смотрит виджет.

    🔴 Раньше собирались только value_field/plan_field/fact_field, и имена граф
    у «Сравнения», тепловой карты, карточки в разрезах, полос план-факта и
    таблицы грузились лишь «за компанию» — если на той же странице стоял
    виджет с одной графой. Одинокое «Сравнение» говорило «Графы формы: …»
    пустым списком (находка 24.09.2026 при разборе ⓘ).
    """
    codes: List[str] = []
    for key in ("value_field", "plan_field", "fact_field"):
        if cfg.get(key):
            codes.append(cfg[key])
    codes += [c for c in (cfg.get("value_fields") or []) if c]
    for p in cfg.get("pairs") or []:
        codes += [c for c in (p.get("plan_field"), p.get("fact_field")) if c]
    return codes


async def load_context(conn, org_id, widgets: List[dict]) -> dict:
    """Метрики, графы и имена форм для пачки виджетов — по одному запросу на вид."""
    metric_codes: set = set()
    ds_codes: set = set()
    for w in widgets:
        cfg = w.get("config") or {}
        for key in ("metric_code", "plan_metric", "fact_metric"):
            if cfg.get(key):
                metric_codes.add(cfg[key])
        if cfg.get("dataset_code"):
            ds_codes.add(cfg["dataset_code"])
    return {"metrics": await _metrics_info(conn, org_id, metric_codes),
            **await _forms_and_fields(conn, org_id, ds_codes)}


async def _metrics_info(conn, org_id, codes: set) -> dict:
    if not codes:
        return {}
    rows = await conn.fetch(
        "select m.code, m.name, m.description, m.info_text, "
        # Ответственный за показатель (п. 11): «к кому идти с вопросом» —
        # часть ответа на «что это за цифра», а не отдельная справка.
        "  (select coalesce(nullif(u.full_name,''), u.login) from users u where u.id=m.owner_id) as owner_name, "
        "  (select mv.formula_expression from metric_versions mv where mv.metric_id=m.id "
        f"   order by {_BEST_VER} limit 1) as formula, "
        "  (select mv.status::text from metric_versions mv where mv.metric_id=m.id "
        f"   order by {_BEST_VER} limit 1) as status, "
        "  (select mv.unit from metric_versions mv where mv.metric_id=m.id "
        f"   order by {_BEST_VER} limit 1) as unit "
        "from metrics m where m.organization_id=$1 and m.code = any($2::text[])",
        org_id, list(codes))
    return {r["code"]: dict(r) for r in rows}


async def _forms_and_fields(conn, org_id, codes: set) -> dict:
    """Имя формы и графы каждого набора — по ПОСЛЕДНЕМУ действующему выпуску.

    🔴 Прежний запрос брал `distinct` по ВСЕМ выпускам без порядка, и имя формы
    в ⓘ было случайным: у ведомств «Статистики услуг» по пять имён («ЗАГС —
    2026-08-05» … «ЗАГС: услуги в МФЦ ДНР»), у формы МАХ — «Приложение_к_
    Протоколу… .xlsx». Подпись формы под заголовком при этом бралась по
    последнему выпуску — две части одной карточки называли форму по-разному.
    Теперь обе берут последний выпуск и чистят имя `form_title`. Заодно запрос
    перестал перемножать 201 выпуск на 400 граф (145 мс на каждое открытие
    страницы РЦО).
    """
    if not codes:
        return {"fields": {}, "forms": {}}
    from ._suggest import form_title

    latest = await conn.fetch(
        "select distinct on (code) code, name, object_id from dataset_releases "
        "where organization_id=$1 and code = any($2::text[]) and status <> 'superseded' "
        "order by code, reporting_period_start desc nulls last, created_at desc",
        org_id, list(codes))
    forms = {r["code"]: form_title(r["name"]) for r in latest}
    by_object: Dict[str, str] = {str(r["object_id"]): r["code"] for r in latest}
    fields: Dict[tuple, dict] = {}
    if by_object:
        rows = await conn.fetch(
            "select object_id, code, name, description, unit from canonical_fields "
            "where object_id = any($1::uuid[])", list(by_object))
        for r in rows:
            ds = by_object[str(r["object_id"])]
            fields[(ds, r["code"])] = {"name": r["name"], "description": r["description"],
                                       "unit": r["unit"], "dataset_code": ds,
                                       "dataset_name": forms.get(ds) or ds}
    return {"fields": fields, "forms": forms}


# --------------------------------------------------------------------------- #
# Части пояснения по виду виджета — чистая функция, без БД
# --------------------------------------------------------------------------- #

def _metric_text(info: dict) -> str:
    parts = [f"Показатель «{info['name']}»."]
    # Описание, заданное человеком, важнее машинного: оно объясняет СМЫСЛ,
    # а формула — только способ счёта.
    human = (info.get("description") or "").strip() or (info.get("info_text") or "").strip()
    if human:
        parts.append(human)
    if info.get("formula"):
        parts.append(f"Считается: {info['formula']}.")
    status = _STATUS_RU.get(info.get("status") or "")
    if status:
        # Про черновик молчать нельзя: на карточке предварительное значение
        # выглядит ровно так же, как утверждённое.
        parts.append(status[0].upper() + status[1:] + ".")
    if info.get("owner_name"):
        # Ответственный — последним: сначала что за цифра, потом к кому с ней идти.
        parts.append(f"Ответственный: {info['owner_name']}.")
    return " ".join(parts)


class _Ctx:
    """Справочники в удобном для текста виде."""

    def __init__(self, ctx: dict, cfg: dict):
        self.metrics = ctx.get("metrics") or {}
        self.fields = ctx.get("fields") or {}
        self.forms = ctx.get("forms") or {}
        self.cfg = cfg
        self.ds = cfg.get("dataset_code")

    def info(self, code: Optional[str]) -> Optional[dict]:
        return self.fields.get((self.ds, code)) if code else None

    def name(self, code: Optional[str]) -> str:
        i = self.info(code)
        return i["name"] if i else (code or "")

    def form(self) -> str:
        return self.forms.get(self.ds) or (self.ds or "")

    def quoted(self, codes: List[str], limit: int = 4) -> str:
        names = [f"«{self.name(c)}»" for c in codes if c]
        head = ", ".join(names[:limit])
        return head + (f" и ещё {len(names) - limit}" if len(names) > limit else "")


def _rows_fold(name: str, unit: Optional[str] = None) -> str:
    """Как сворачиваются СТРОКИ формы — половина ответа «что это за число»."""
    if is_share(name, unit):
        return "Строки формы усредняются: доли и проценты складывать нельзя."
    return "Значение — сумма по строкам формы."


def _month_fold(name: str) -> str:
    """Как собирается месяц из отчётов — то же правило, что считает виджет."""
    from ._widgetcalc import fold_of  # локально: _widgetcalc тяжёлый и тянет источники

    return {"avg": "Месяц — среднее по его отчётам: доли складывать нельзя.",
            "last": "Месяц — ПОСЛЕДНИЙ отчёт месяца: нарастающий итог уже содержит "
                    "предыдущие, и сумма дала бы несуществующее число.",
            }.get(fold_of(name), "Месяц — сумма его отчётов.")


def _data_of(c: _Ctx, codes: List[str]) -> str:
    if not c.ds:
        return ""
    body = f"Форма «{c.form()}»"
    if codes:
        body += f", {'графа' if len(codes) == 1 else 'графы'} {c.quoted(codes)}"
    desc = next(((c.info(x) or {}).get("description") or "" for x in codes[:1]), "").strip()
    unit = next(((c.info(x) or {}).get("unit") or "" for x in codes[:1]), "") or c.cfg.get("unit")
    body += "."
    if desc:
        body += f" {desc}"
    if unit:
        body += f" Единица: {unit}."
    return body


def _period_note(cfg: dict) -> str:
    if cfg.get("period"):
        return (f"Закреплён отчёт за {_ru_day(cfg['period'])} — новые файлы виджет не "
                "меняют (срез).")
    return ""


def _join(*parts: str) -> str:
    return " ".join(p for p in parts if p)


def widget_sections(w: dict, ctx: dict) -> Dict[str, str]:
    """Части пояснения виджета. Пусто там, где сказать нечего.

    Чистая функция: ей хватает вида, конфигурации и справочников `load_context`,
    поэтому её одинаково зовут и страница дашборда (ⓘ), и предложение виджетов
    для ещё не созданных кандидатов.
    """
    cfg = w.get("config") or {}
    t = w.get("widget_type") or ""
    c = _Ctx(ctx, cfg)
    s: Dict[str, str] = {}
    vf = cfg.get("value_field")
    vfs = [x for x in (cfg.get("value_fields") or []) if x]
    per = _period_note(cfg)

    if t in ("text", "image"):
        return {}

    # Расчётный показатель (метрика) — его текст одинаков для всех видов.
    if cfg.get("metric_code") and cfg["metric_code"] in c.metrics:
        s["what"] = _metric_text(c.metrics[cfg["metric_code"]])
        s["answers"] = "Сколько сейчас по показателю и откуда эта цифра."
        s["caveats"] = per
        return {k: v for k, v in s.items() if v}

    if t == "plan_fact":
        plan, fact = cfg.get("plan_metric"), cfg.get("fact_metric")
        if plan and fact and plan in c.metrics and fact in c.metrics:
            s["what"] = (f"План — показатель «{c.metrics[plan]['name']}», "
                         f"факт — «{c.metrics[fact]['name']}».")
        elif c.info(cfg.get("plan_field")) and c.info(cfg.get("fact_field")):
            s["what"] = (f"План — графа «{c.name(cfg['plan_field'])}», факт — "
                         f"«{c.name(cfg['fact_field'])}» из формы «{c.form()}».")
        else:
            return {}
        s["answers"] = "Выполняется ли план и насколько."
        s["how"] = "Полоса показывает выполнение в процентах: факт делённый на план."
        s["caveats"] = _join("Пороги красят недобор." if cfg.get("alerts") else "", per)
        return {k: v for k, v in s.items() if v}

    if cfg.get("formula"):
        return {"what": f"Значение считается формулой: {cfg['formula']}.", "caveats": per}

    if t == "field_list":
        what = f"выбранные графы ({len(vfs)})" if vfs else "все графы"
        s["what"] = f"{what.capitalize()} формы «{c.form()}» — строками, с приростом к прошлому отчёту."
        s["answers"] = "Какие показатели идут и в каком объёме — в том числе внутри одной строки формы."
        s["how"] = ("Строки формы свёрнуты: количества сложены, доли усреднены. Доля показывается, "
                    "только когда все графы измеряют одно и то же, — складывать принятые с "
                    "выданными нельзя, это стадии одного обращения.")
        s["caveats"] = _join("Графа-итог находится по арифметике и в доле не участвует.", per)
        return {k: v for k, v in s.items() if v}

    if t == "ranked":
        measure = cfg.get("measure")
        base = (f"Графа «{c.name(vf)}»" if vf else
                f"Мера «{measure}» (свод всех граф с этим хвостом)" if measure else "Показатель")
        by_plan = cfg.get("rank_by") == "plan_pct" and cfg.get("plan_field")
        s["what"] = f"{base} по строкам формы «{c.form()}»: топ и антитоп полосами."
        s["answers"] = "Кто впереди и кто в хвосте."
        s["how"] = ("Порядок — по выполнению плана, поэтому крупная строка не выигрывает "
                    "автоматически." if by_plan else "Порядок — по величине.")
        s["caveats"] = _join("Длина полосы считается от максимума по ВСЕМ строкам, а не по "
                             "показанным. Середина списка свёрнута, её размер назван под таблицей.", per)
        return {k: v for k, v in s.items() if v}

    if t == "spark_table":
        s["what"] = f"Графа «{c.name(vf)}» по каждой строке формы: линия за последние отчёты, текущее значение и изменение."
        s["answers"] = "Кто за последние отчёты просел или вырос — раньше, чем это видно в месячных итогах."
        s["data"] = _data_of(c, [vf] if vf else [])
        s["how"] = "Прирост считается к предыдущему НЕПУСТОМУ отчёту — пропуск в форме это не ноль."
        s["caveats"] = per
        return {k: v for k, v in s.items() if v}

    if t == "bullet":
        pairs = cfg.get("pairs") or []
        facts = [p.get("fact_field") for p in pairs]
        s["what"] = f"Пар «план + факт»: {len(pairs)} — у каждой своя полоса выполнения и отметка плана."
        s["answers"] = "Какой показатель отстаёт от плана."
        s["data"] = _data_of(c, facts)
        s["how"] = ("Шкала общая — 100 % это план у каждой строки, поэтому показатели разного "
                    "масштаба сравнимы между собой.")
        s["caveats"] = _join("Полоса, упёршаяся в потолок шкалы, помечена зубцом, но само число "
                             "печатается всегда.", per)
        return {k: v for k, v in s.items() if v}

    if t == "thermometer":
        due = _ru_day(cfg.get("deadline"))
        s["what"] = (f"План — графа «{c.name(cfg.get('plan_field'))}», факт — "
                     f"«{c.name(cfg.get('fact_field'))}»: слева выполнено, справа — сколько прошло срока до {due}.")
        s["answers"] = "Успеваем ли к сроку и сколько нужно в день."
        s["how"] = ("Отсчёт идёт от первого отчёта формы, а не от выдуманной даты. Опережение и "
                    "отставание — в процентных пунктах.")
        s["caveats"] = per
        return {k: v for k, v in s.items() if v}

    if t == "matrix":
        month = cfg.get("period_group") == "month"
        cols = "месяцам" if month else "отчётам"
        if vf:
            s["what"] = f"Графа «{c.name(vf)}» по каждой строке формы и по {cols}."
            s["answers"] = "У какой строки какой был период — найти просевшие и выросшие."
            s["how"] = _join("Строки формы НЕ сворачиваются — значение показано по каждой.",
                             _month_fold(c.name(vf)) if month else "",
                             "Под значением — изменение к прошлому столбцу, в колонке «За период» — "
                             "от первого показанного к последнему.")
            s["data"] = _data_of(c, [vf])
        elif vfs:
            s["what"] = f"Показатели формы по {cols}: {c.quoted(vfs)}."
            s["answers"] = "Как менялся каждый показатель формы."
            s["how"] = _join("Строки формы свёрнуты (количества сложены, доли усреднены).",
                             "Месяц собирается по смыслу графы: поток складывается, нарастающий "
                             "итог берётся последним отчётом, доля усредняется." if month else "")
            s["data"] = _data_of(c, [])
        else:
            return {}
        s["caveats"] = _join("Месяцы бывают неравны по числу отчётов — это сказано над таблицей."
                             if month else "", per)
        return {k: v for k, v in s.items() if v}

    if t == "dynamics" and vf:
        month = cfg.get("period_group") == "month"
        s["what"] = f"Линия графы «{c.name(vf)}» по {'месяцам' if month else 'отчётам'}."
        s["answers"] = "Как показатель менялся со временем."
        s["data"] = _data_of(c, [vf])
        s["how"] = _join(_rows_fold(c.name(vf), (c.info(vf) or {}).get("unit")),
                         _month_fold(c.name(vf)) if month else "")
        s["caveats"] = _join("Число отчётов в каждом месяце названо под графиком: неравные "
                             "месяцы нельзя сравнивать напрямую." if month else "", per)
        return {k: v for k, v in s.items() if v}

    if t == "status_grid" and vf:
        s["what"] = f"Плитка на каждую строку формы по графе «{c.name(vf)}»."
        if cfg.get("plan_field"):
            s["what"] += f" Цвет — по выполнению плана «{c.name(cfg['plan_field'])}»."
            s["answers"] = "У кого из строк плохо — с одного взгляда."
        else:
            s["answers"] = "Как значение распределено по строкам формы."
            s["caveats"] = ("Цвет ставится по порогам. Без плана и без заданных порогов все "
                            "плитки одного цвета.")
        s["data"] = _data_of(c, [vf])
        s["caveats"] = _join(s.get("caveats", ""), per)
        return {k: v for k, v in s.items() if v}

    if t in ("bar", "line") and vf:
        s["what"] = f"Графа «{c.name(vf)}» по строкам формы."
        s["answers"] = "Как значение распределено по строкам и кто выделяется."
        s["data"] = _data_of(c, [vf])
        s["caveats"] = _join("На широкой форме показаны самые крупные строки — число скрытых "
                             "названо под графиком, полный список — в таблице.", per)
        return {k: v for k, v in s.items() if v}

    if t == "pie" and vf:
        s["what"] = f"Доли строк формы в графе «{c.name(vf)}»."
        s["answers"] = "Какая строка даёт какую часть целого."
        s["data"] = _data_of(c, [vf])
        s["caveats"] = _join("Больше семи секторов не рисуем: мелкие строки сложены в «Прочие», "
                             "целое не меняется.", per)
        return {k: v for k, v in s.items() if v}

    if t == "waterfall" and vf:
        by_periods = cfg.get("by") == "periods"
        if by_periods:
            s["what"] = f"Ступени графы «{c.name(vf)}» по периодам и итоговый столбик."
            s["answers"] = "За счёт каких периодов набран итог."
            from ._widgetcalc import fold_of

            s["how"] = ("Графа — нарастающий итог: первая ступень — уровень, с которого начали, "
                        "дальше — прирост каждого периода." if fold_of(c.name(vf)) == "last"
                        else "Ступень — значение периода (поток складывается).")
            s["caveats"] = _join("Больше двенадцати отчётов сворачиваются в месяцы. Сумма "
                                 "ступеней всегда равна итогу.", per)
        else:
            s["what"] = f"Вклад строк формы в графу «{c.name(vf)}»."
            s["answers"] = "Из каких строк сложился итог."
            s["caveats"] = _join("Мелкие строки сложены в «Прочие», чтобы сумма сходилась.", per)
        s["data"] = _data_of(c, [vf])
        return {k: v for k, v in s.items() if v}

    if t == "yoy" and vf:
        s["what"] = f"Графа «{c.name(vf)}» по месяцам: текущий год против прошлого."
        s["answers"] = "Лучше или хуже, чем год назад в тот же месяц."
        s["data"] = _data_of(c, [vf])
        s["caveats"] = per
        return {k: v for k, v in s.items() if v}

    if t == "kpi_group" and vfs:
        s["what"] = f"Показатель в {len(vfs)} разрезах одной карточкой: {c.quoted(vfs)}."
        s["answers"] = "Сколько по показателю в каждом разрезе и как это изменилось."
        s["data"] = _data_of(c, [])
        s["how"] = _join(_rows_fold(c.name(vfs[0])),
                         "Под каждой строкой — изменение к прошлому отчёту." if cfg.get("compare_prev") else "")
        s["caveats"] = per
        return {k: v for k, v in s.items() if v}

    if t == "compare" and vfs:
        s["what"] = f"Графы {c.quoted(vfs)} рядом по строкам формы."
        s["answers"] = "Как соотносятся показатели между собой."
        s["data"] = _data_of(c, [])
        s["caveats"] = _join("На широкой форме показаны самые крупные строки и показатели — "
                             "сколько скрыто, сказано под графиком.", per)
        return {k: v for k, v in s.items() if v}

    if t == "heatmap" and vfs:
        s["what"] = f"Строки формы × графы {c.quoted(vfs)}; цвет — величина."
        s["answers"] = "Где концентрируется нагрузка: какая графа у какой строки."
        s["data"] = _data_of(c, [])
        s["caveats"] = _join("Когда значения различаются в разы, оттенки делят клетки поровну, а "
                             "границы оттенков подписаны числами в легенде.", per)
        return {k: v for k, v in s.items() if v}

    if t == "funnel" and vfs:
        s["what"] = f"Ступени воронки: {c.quoted(vfs, 6)}."
        s["answers"] = "Сколько дошло с шага на шаг и где теряются."
        s["data"] = _data_of(c, [])
        s["caveats"] = per
        return {k: v for k, v in s.items() if v}

    if t == "pivot" and vfs:
        s["what"] = f"Строки формы × графы {c.quoted(vfs)} с итогами."
        s["answers"] = "Сколько по каждой строке и графе и сколько всего."
        s["how"] = ("Свод («ИТОГО») с частями не складывается; итога нет вовсе, если показаны "
                    "разные меры — это сказано над таблицей.")
        s["caveats"] = per
        return {k: v for k, v in s.items() if v}

    if t == "table" and c.ds:
        s["what"] = f"Первичные данные формы «{c.form()}»: строки и графы последнего отчёта."
        s["answers"] = "Откуда взялась любая цифра на других страницах."
        s["caveats"] = _join("Есть поиск, сортировка и выгрузка в Excel.", per)
        return {k: v for k, v in s.items() if v}

    # Остальные виды с одной графой (kpi, gauge, dynamics без графы и т. п.).
    if c.ds and vf and c.info(vf):
        info = c.info(vf) or {}
        s["what"] = f"Графа «{info['name']}» из формы «{c.form()}»."
        if (info.get("description") or "").strip():
            s["what"] += f" {info['description'].strip()}"
        unit = info.get("unit") or cfg.get("unit")
        s["answers"] = ("Какая доля сейчас — видно на шкале." if t == "gauge"
                        else "Сколько сейчас.")
        s["how"] = _join(f"Единица: {unit}." if unit else "", _rows_fold(info["name"], unit))
        extra = []
        if cfg.get("compare_prev"):
            extra.append("Под числом — изменение к прошлому отчёту.")
        if cfg.get("spark"):
            extra.append("Мини-график — движение по отчётам; значения видны при наведении.")
        s["caveats"] = _join(*extra, per)
        return {k: v for k, v in s.items() if v}

    if vfs:
        return {"what": f"Графы формы: {c.quoted(vfs, 5)}.", "caveats": per}
    if c.ds:
        return {"what": f"Первичные данные формы «{c.form()}».", "caveats": per}
    return {}


# --------------------------------------------------------------------------- #
# Входы: пачкой на страницу
# --------------------------------------------------------------------------- #

async def explain_sections(conn, org_id, widgets: List[dict]) -> Dict[str, Dict[str, str]]:
    """{id: части пояснения} — для предложения виджетов (кандидаты с синтетическим id)."""
    ctx = await load_context(conn, org_id, widgets)
    out: Dict[str, Dict[str, str]] = {}
    for w in widgets:
        sec = widget_sections(w, ctx)
        if sec:
            out[str(w["id"])] = sec
    return out


async def explain_widgets(conn, org_id, widgets: List[dict]) -> Dict[str, str]:
    """{id виджета: текст ⓘ}. Пусто там, где сказать нечего.

    Текст — склейка тех же частей, что показывает предложение виджетов.
    """
    ctx = await load_context(conn, org_id, widgets)
    out: Dict[str, str] = {}
    for w in widgets:
        text = sections_text(widget_sections(w, ctx))
        if text:
            out[str(w["id"])] = _clip(text)
    return out


async def widget_captions(conn, org_id, widgets: List[dict]) -> Dict[str, str]:
    """{id виджета: короткая подпись «по какой форме»}.

    🔴 Заведено по замечанию заказчика: на карточке написано «Выдано, ед.», и
    непонятно — выдано ЧЕГО. В самой форме этого слова нет: графа называется
    буквально «ИТОГО · Выдано, ед.», и выдумать «обращений» нельзя — придуманное
    пояснение к государственному показателю хуже отсутствующего.

    Но форма называет СЕБЯ: «РЦО: ежедневный отчёт в разрезе отделов и услуг».
    Это и есть честный ответ на «чего»: раз отчёт по услугам, значит принято и
    выдано — по услугам. Поэтому подпись — имя формы, а не выдуманный предмет.

    Подпись не показывается там, где она ничего не добавляет: если имя виджета
    и так начинается с имени формы (так называет их авто-сборка у таблиц и
    графиков), повторять его под заголовком незачем.
    """
    from ._suggest import form_title

    codes = sorted({str((w["config"] or {}).get("dataset_code")) for w in widgets
                    if (w["config"] or {}).get("dataset_code")})
    if not codes:
        return {}
    rows = await conn.fetch(
        "select distinct on (code) code, name from dataset_releases "
        "where organization_id=$1 and code = any($2::text[]) and status <> 'superseded' "
        "order by code, reporting_period_start desc nulls last, created_at desc",
        org_id, codes)
    names = {r["code"]: form_title(r["name"]) for r in rows}

    out: Dict[str, str] = {}
    for w in widgets:
        cfg = w["config"] or {}
        code = cfg.get("dataset_code")
        title = names.get(code)
        if not title:
            continue
        out[str(w["id"])] = title
    return out


def widget_configs(rows) -> List[dict]:
    """Виджеты в виде, удобном для разбора: config уже словарь."""
    return [{"id": r["id"], "widget_type": r["widget_type"], "config": _cfg(r)} for r in rows]
