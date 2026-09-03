"""Что за цифра в виджете — текст для значка ⓘ.

Раньше ⓘ объяснял ТИП виджета («карточка показывает одно число»), то есть то,
что и так видно. Человек, глядя на «929 825», спрашивает другое: что это за
число, откуда взято и можно ли ему верить.

Собирается пачкой на всю страницу (два запроса на список виджетов, а не по
запросу на каждый): подсказка нужна сразу при наведении, догружать её по
одному значку — значит показать пустоту в тот момент, когда на неё смотрят.

Ничего не выдумываем: если описание не задано, так и говорим. Придуманное
пояснение к государственному показателю хуже отсутствующего.
"""
from __future__ import annotations

from typing import Dict, List

from ._aggregate import is_share
from ._alerts import _cfg

# Подсказка — не статья: длинный текст в облачке никто не дочитывает, а
# полный разбор доступен по кнопке «🔍 подробнее».
MAX_EXPLAIN = 400

_STATUS_RU = {
    "approved": "формула одобрена",
    "validated": "формула проверена, ждёт одобрения",
    "draft": "формула в черновике — значение предварительное",
    "deprecated": "формула устарела",
}


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_EXPLAIN else text[:MAX_EXPLAIN - 1].rstrip() + "…"


async def explain_widgets(conn, org_id, widgets: List[dict]) -> Dict[str, str]:
    """{id виджета: пояснение}. Пусто там, где сказать нечего."""
    metric_codes: set = set()
    field_keys: set = set()
    for w in widgets:
        cfg = w["config"]
        for key in ("metric_code", "plan_metric", "fact_metric"):
            if cfg.get(key):
                metric_codes.add(cfg[key])
        ds = cfg.get("dataset_code")
        if ds:
            for key in ("value_field", "plan_field", "fact_field"):
                if cfg.get(key):
                    field_keys.add((ds, cfg[key]))

    metrics = await _metrics_info(conn, org_id, metric_codes)
    fields = await _fields_info(conn, org_id, field_keys)

    out: Dict[str, str] = {}
    for w in widgets:
        text = _explain_one(w, metrics, fields)
        if text:
            out[str(w["id"])] = _clip(text)
    return out


async def _metrics_info(conn, org_id, codes: set) -> dict:
    if not codes:
        return {}
    rows = await conn.fetch(
        "select m.code, m.name, m.description, m.info_text, "
        # Ответственный за показатель (п. 11): «к кому идти с вопросом» —
        # часть ответа на «что это за цифра», а не отдельная справка.
        "  (select coalesce(nullif(u.full_name,''), u.login) from users u where u.id=m.owner_id) as owner_name, "
        "  (select mv.formula_expression from metric_versions mv where mv.metric_id=m.id "
        "   order by case mv.status when 'approved' then 0 when 'validated' then 1 "
        "                           when 'draft' then 2 else 3 end, mv.version_no desc limit 1) as formula, "
        "  (select mv.status::text from metric_versions mv where mv.metric_id=m.id "
        "   order by case mv.status when 'approved' then 0 when 'validated' then 1 "
        "                           when 'draft' then 2 else 3 end, mv.version_no desc limit 1) as status, "
        "  (select mv.unit from metric_versions mv where mv.metric_id=m.id "
        "   order by case mv.status when 'approved' then 0 when 'validated' then 1 "
        "                           when 'draft' then 2 else 3 end, mv.version_no desc limit 1) as unit "
        "from metrics m where m.organization_id=$1 and m.code = any($2::text[])",
        org_id, list(codes))
    return {r["code"]: dict(r) for r in rows}


async def _fields_info(conn, org_id, keys: set) -> dict:
    """Описание граф формы. Ключ — пара (код датасета, код поля): один и тот же
    код поля у разных объектов означает разные показатели."""
    if not keys:
        return {}
    codes = list({ds for ds, _f in keys})
    rows = await conn.fetch(
        "select distinct r.code as dataset_code, r.name as dataset_name, "
        "  cf.code as field_code, cf.name, cf.description, cf.unit "
        "from dataset_releases r "
        "join canonical_fields cf on cf.object_id = r.object_id "
        "where r.organization_id=$1 and r.code = any($2::text[]) and r.status <> 'superseded'",
        org_id, codes)
    return {(r["dataset_code"], r["field_code"]): dict(r) for r in rows}


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


def _field_text(info: dict, cfg: dict) -> str:
    parts = [f"Графа «{info['name']}» из формы «{info.get('dataset_name') or info['dataset_code']}»."]
    if (info.get("description") or "").strip():
        parts.append(info["description"].strip())
    unit = info.get("unit") or cfg.get("unit")
    if unit:
        parts.append(f"Единица: {unit}.")
    # Как сворачиваются строки — половина ответа на вопрос «что это за число»:
    # у формы с районами карточка показывает не значение, а свод по ним.
    if is_share(info.get("name"), unit):
        parts.append("Строки формы усредняются: доли и проценты складывать нельзя.")
    else:
        parts.append("Значение — сумма по строкам формы.")
    return " ".join(parts)


def _explain_one(w: dict, metrics: dict, fields: dict) -> str:
    cfg = w["config"]
    t = w["widget_type"]

    if t == "plan_fact":
        plan, fact = cfg.get("plan_metric"), cfg.get("fact_metric")
        if plan and fact and plan in metrics and fact in metrics:
            return (f"План — показатель «{metrics[plan]['name']}», "
                    f"факт — «{metrics[fact]['name']}». Полоса показывает выполнение в процентах.")
        ds = cfg.get("dataset_code")
        pf, ff = fields.get((ds, cfg.get("plan_field"))), fields.get((ds, cfg.get("fact_field")))
        if pf and ff:
            return (f"План — графа «{pf['name']}», факт — «{ff['name']}» "
                    f"из формы «{pf.get('dataset_name') or ds}». Полоса показывает выполнение в процентах.")
        return ""

    # Виды, добавленные в этапе 2. Без своего текста они падали в общее
    # «Первичные данные формы …», которое не объясняет, ЧТО именно показано, —
    # а именно за этим значок ⓘ и открывают.
    if t == "field_list":
        ds = cfg.get("dataset_code")
        any_ds = next((v for k, v in fields.items() if k[0] == ds), None)
        form = (any_ds or {}).get("dataset_name") or ds
        picked = cfg.get("value_fields") or []
        what = f"выбранные графы ({len(picked)})" if picked else "все графы"
        return (f"{what.capitalize()} формы «{form}» — строками, с приростом к прошлому отчёту. "
                "Строки формы (отделения) свёрнуты: количества сложены, доли усреднены. "
                "Доля показывается, только когда все графы измеряют одно и то же, — "
                "складывать принятые с выданными нельзя, это стадии одного обращения. "
                "Графа-итог находится по арифметике и в доле не участвует.")

    if t == "ranked":
        ds, field = cfg.get("dataset_code"), cfg.get("value_field")
        info = fields.get((ds, field))
        base = f"Графа «{info['name']}»" if info else "Показатель"
        by_plan = cfg.get("rank_by") == "plan_pct"
        return (f"{base} по строкам формы: топ и антитоп. "
                + ("Порядок — по выполнению плана, поэтому крупная строка не выигрывает "
                   "автоматически. " if by_plan else "Порядок — по величине. ")
                + "Длина полосы считается от максимума по ВСЕМ строкам, а не по показанным. "
                  "Середина списка свёрнута, её размер назван под таблицей.")

    if t == "spark_table":
        ds, field = cfg.get("dataset_code"), cfg.get("value_field")
        info = fields.get((ds, field))
        base = f"Графа «{info['name']}»" if info else "Показатель"
        return (f"{base} по каждой строке формы: линия за последние отчёты, текущее значение и "
                "изменение. Прирост считается к предыдущему НЕПУСТОМУ отчёту — пропуск в форме "
                "это не ноль.")

    if t == "bullet":
        pairs = cfg.get("pairs") or []
        return (f"Пар «план + факт»: {len(pairs)}. Шкала общая — 100 % это план у каждой строки, "
                "поэтому показатели разного масштаба сравнимы между собой. Полоса, упёршаяся "
                "в потолок шкалы, помечена зубцом, но само число печатается всегда.")

    if t == "thermometer":
        ds = cfg.get("dataset_code")
        pf = fields.get((ds, cfg.get("plan_field")))
        ff = fields.get((ds, cfg.get("fact_field")))
        due = cfg.get("deadline")
        base = (f"План — графа «{pf['name']}», факт — «{ff['name']}». " if pf and ff else "")
        return (base + f"Слева выполнено, справа — сколько прошло срока до {due}. "
                "Отсчёт идёт от первого отчёта формы, а не от выдуманной даты. "
                "Опережение и отставание — в процентных пунктах.")

    if t == "matrix":
        # У матрицы строки формы НЕ сворачиваются — значение показано по
        # каждой отдельно; общий текст про «сумму по строкам» соврал бы.
        ds, field = cfg.get("dataset_code"), cfg.get("value_field")
        info = fields.get((ds, field))
        if info:
            return (f"Графа «{info['name']}» из формы «{info.get('dataset_name') or ds}» "
                    f"по каждой строке за каждый отчёт. Под значением — изменение к прошлому отчёту, "
                    f"в колонке «За период» — от первого показанного отчёта к последнему.")
        return ""

    if cfg.get("metric_code") and cfg["metric_code"] in metrics:
        return _metric_text(metrics[cfg["metric_code"]])

    if cfg.get("formula"):
        return f"Значение считается формулой: {cfg['formula']}."

    ds, field = cfg.get("dataset_code"), cfg.get("value_field")
    if ds and field and (ds, field) in fields:
        return _field_text(fields[(ds, field)], cfg)

    # Несколько полей (сравнение, тепловая карта, сводная): перечисляем графы.
    names = [fields[(ds, f)]["name"] for f in (cfg.get("value_fields") or []) if (ds, f) in fields]
    if names:
        shown = ", ".join(f"«{n}»" for n in names[:5])
        tail = f" и ещё {len(names) - 5}" if len(names) > 5 else ""
        return f"Графы формы: {shown}{tail}."

    if ds:
        any_ds = next((v for k, v in fields.items() if k[0] == ds), None)
        if any_ds:
            return f"Первичные данные формы «{any_ds.get('dataset_name') or ds}»."
    return ""


def widget_configs(rows) -> List[dict]:
    """Виджеты в виде, удобном для разбора: config уже словарь."""
    return [{"id": r["id"], "widget_type": r["widget_type"], "config": _cfg(r)} for r in rows]
