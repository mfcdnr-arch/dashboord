"""Проверки качества данных перед выпуском: сверка с прошлой неделей и
арифметика ВНУТРИ файла.

Форму заполняет человек, и самые дорогие ошибки — не опечатки, а перенос
прошлых цифр. Реальный случай заказчика (05.08.2026): строка «Донецкая Народная
Республика» в новом отчёте совпала с отчётом за 29.07 посимвольно — данные
неделю не обновляли, а система приняла их молча и показала на дашборде как
свежие.

Проверки НЕ блокируют выпуск: решение за человеком, а ошибочный выпуск в
системе обратим («Отменить выпуск»). Задача — не дать пропустить подозрительное
молча. Поэтому все правила формулируются как «проверьте», а не «нельзя».

Правила опираются на устройство имён госформ («Показатель · Роль · Разрез»),
разбор которых уже живёт в metrics/data_suggestions — переиспользуем его, чтобы
система не противоречила сама себе.

Проверок ДВА рода, и это разделение существенное:

* `compare_with_previous` — сверка с прошлым выпуском. Без прошлого отчёта
  бессмысленна и возвращает пусто.
* `check_internal` — арифметика внутри ОДНОГО файла: сумма по строкам против
  строки «Итого», значение за неделю против накопительного итога, факт против
  плана. Ей прошлый отчёт не нужен — и именно поэтому она вынесена отдельно:
  раньше правило «за неделю больше итога» жило внутри сверки с прошлым и
  вместе с ней МОЛЧАЛО на первом файле формы, то есть ровно там, где
  ошибку ещё никто не мог заметить.

Оба рода запускаются одной `check_release` — чтобы три места, где эти
замечания показываются (предпросмотр выпуска, результат выпуска и блок «На что
посмотреть» на дашборде), не могли разойтись между собой.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

from ..metrics.data_suggestions import _clean, _is_main_slice, _split_name, _subject_key

# Ключ значения: (название строки, код показателя)
Key = Tuple[str, str]


def classify_slice(field_name: str) -> str:
    """Разрез показателя: cumulative | weekly | other.

    «Нарастающим итогом» — накопление с начала периода: такое значение по
    определению не может уменьшиться. «За отчётную неделю» — срез, он всегда
    часть накопленного. Остальное (например «текущий месяц») не сравниваем:
    месячный накопительный итог законно падает при смене месяца.
    """
    slc = _clean(_split_name(field_name)["slice"]).lower()
    if "недел" in slc:
        return "weekly"
    if _is_main_slice(slc):
        return "cumulative"
    return "other"


def _fmt(v: float) -> str:
    return f"{v:,.0f}".replace(",", " ") if float(v).is_integer() else f"{v:,.2f}".replace(",", " ")


# Строка-итог госформы: «Итого», «Всего», «ИТОГО по региону». Ищем ЯВНУЮ
# подпись — строку вроде «Донецкая Народная Республика», которая по смыслу тоже
# свод, распознать нельзя, и гадать система не должна.
_TOTAL_ROW_RE = re.compile(r"итог|всего", re.IGNORECASE)

# Допуск при сверке суммы с итогом. Ноль тут не годится: в формах округляют, и
# расхождение в единицу — не ошибка заполнения, а следствие округления. Зато
# пропущенный район или опечатка дают расхождение на порядки.
TOTAL_TOLERANCE_ABS = 1.0
TOTAL_TOLERANCE_REL = 0.005

# Признак «отчёт получен умножением предыдущего»: сколько показателей должны
# сойтись и насколько узкой должна быть полоса их коэффициентов роста.
#
# Числа подобраны ЗАМЕРОМ на всех формах дев-стенда, а не на глаз. Два отчёта
# формы МАХ (12.08 и 19.08.2026) дали полосу 0,00003 и 0,00006 при 13
# показателях; самая узкая полоса на ЖИВЫХ данных — 0,00162 у «Минобороны»
# (и там всего 2 показателя). Порог 0,001 лежит между ними с запасом в 27 раз,
# а минимум в 4 показателя дополнительно отсекает мелкие формы, где совпадение
# двух коэффициентов ещё может быть случайностью.
MIN_FIELDS_MULTIPLIED = 4
MULTIPLIED_BAND = 0.001


def check_internal(current: Dict[Key, float], names: Dict[str, str]) -> List[dict]:
    """Арифметика ВНУТРИ одного файла. Прошлый выпуск не нужен.

    Работает и на ПЕРВОМ файле формы — в этом и смысл: сверка с прошлой неделей
    там молчит, а сумма, не сходящаяся с итогом, видна сразу.
    """
    return [w for w in (_check_total_row(current, names),
                        _check_weekly_over_total(current, names),
                        _check_fact_over_plan(current, names)) if w]


def _check_total_row(current: Dict[Key, float], names: Dict[str, str]) -> Optional[dict]:
    """Сумма по строкам против строки «Итого».

    Считаем только там, где сумма вообще имеет смысл: доли и проценты
    складывать нельзя (правило одно на систему — `dashboards._aggregate`).
    Итоговая строка должна быть РОВНО одна: две «итоговых» подписи означают,
    что мы не понимаем структуру формы, и молчать честнее, чем гадать.
    """
    from ..dashboards._aggregate import is_share  # локально: иначе цикл импорта

    rows = {k[0] for k in current}
    totals = [r for r in rows if _TOTAL_ROW_RE.search(r or "")]
    if len(totals) != 1:
        return None
    total_row = totals[0]

    bad: List[str] = []
    for code in sorted({k[1] for k in current}):
        name = names.get(code, code)
        if is_share(name):
            continue
        total = current.get((total_row, code))
        if total is None:
            continue
        parts = [v for k, v in current.items() if k[1] == code and k[0] != total_row]
        # Одна строка плюс итог — сверять нечего: «сумма» совпадёт с ней самой
        # и правило превратилось бы в проверку «строка равна итогу».
        if len(parts) < 2:
            continue
        diff = sum(parts) - total
        if abs(diff) > max(TOTAL_TOLERANCE_ABS, abs(total) * TOTAL_TOLERANCE_REL):
            bad.append(f"«{name}»: сумма по строкам {_fmt(sum(parts))}, "
                       f"в строке «{total_row}» {_fmt(total)} (расхождение {_fmt(abs(diff))})")
    if not bad:
        return None
    return {"code": "total_row_mismatch", "count": len(bad),
            "message": ("Сумма по строкам не сходится с итоговой строкой — проверьте, все ли "
                        "строки на месте и нет ли опечатки: " + "; ".join(bad[:5]))}


def _check_weekly_over_total(current: Dict[Key, float], names: Dict[str, str]) -> Optional[dict]:
    """Значение за неделю не больше накопительного итога.

    Пары ищем по показателю: у графы «за отчётную неделю» есть графа
    «нарастающим итогом» того же показателя. Неделя — часть накопленного, и
    превышение означает, что графы перепутаны местами.
    """
    cum_by_subject: Dict[str, str] = {}
    for code, name in names.items():
        if classify_slice(name) == "cumulative":
            cum_by_subject.setdefault(_subject_key(_split_name(name)["subject"]), code)

    over: List[str] = []
    for key, cur in current.items():
        name = names.get(key[1], "")
        if classify_slice(name) != "weekly":
            continue
        cum_code = cum_by_subject.get(_subject_key(_split_name(name)["subject"]))
        if cum_code is None:
            continue
        total = current.get((key[0], cum_code))
        if total is not None and cur > total:
            over.append(f"«{name}» в строке «{key[0]}»: за неделю {_fmt(cur)} при итоге {_fmt(total)}")
    if not over:
        return None
    return {"code": "weekly_over_total", "count": len(over),
            "message": ("Значение за неделю больше накопительного итога — похоже, графы перепутаны "
                        "местами: " + "; ".join(over[:5]))}


def _check_fact_over_plan(current: Dict[Key, float], names: Dict[str, str]) -> Optional[dict]:
    """Факт превышает план — но только когда план и факт СОПОСТАВИМЫ.

    🔴 Главное здесь — чего правило НЕ делает. Перевыполнение само по себе не
    ошибка, а у заказчика оно штатное: план задан «до 1 сентября», факт идёт
    нарастающим итогом, и выполнение доходит до 656 %. Правило «факт > план» в
    лоб срабатывало бы каждую неделю по всем показателям и приучило бы
    пропускать замечания вообще — это хуже, чем не иметь правила совсем.

    Поэтому пара берётся, только если у плана и факта ОДИН разрез
    (`classify_slice`): «за неделю» с «за неделю». План на срок («до 1
    сентября») попадает в разрез «other» и с накопительным фактом не
    сопоставляется — проверено на именах граф заказчика. Когда же план задан
    на ту же неделю, что и факт, превышение стоит посмотреть: обычно это
    перепутанные местами графы плана и факта.
    """
    plans: Dict[tuple, str] = {}
    facts: Dict[tuple, str] = {}
    for code, name in names.items():
        parsed = _split_name(name)
        bucket = plans if parsed.get("role") == "plan" else facts if parsed.get("role") == "fact" else None
        if bucket is None:
            continue
        bucket.setdefault((_subject_key(parsed["subject"]), classify_slice(name)), code)

    over: List[str] = []
    for pair, plan_code in plans.items():
        fact_code = facts.get(pair)
        if fact_code is None:
            continue
        for row in sorted({k[0] for k in current}):
            plan_v = current.get((row, plan_code))
            fact_v = current.get((row, fact_code))
            # План 0 — это не «перевыполнение», а незаполненная графа: о ней
            # говорит другое правило, а здесь она дала бы бессмысленное «∞ %».
            if plan_v is None or fact_v is None or plan_v <= 0 or fact_v <= plan_v:
                continue
            over.append(f"«{names.get(fact_code, fact_code)}» в строке «{row}»: "
                        f"факт {_fmt(fact_v)} при плане {_fmt(plan_v)}")
    if not over:
        return None
    return {"code": "fact_over_plan", "count": len(over),
            "message": ("Факт превышает план в том же разрезе — проверьте, не перепутаны ли графы "
                        "плана и факта местами: " + "; ".join(over[:5]))}


def _check_multiplied(current: Dict[Key, float], previous: Dict[Key, float],
                      names: Dict[str, str]) -> Optional[dict]:
    """Все показатели изменились ровно в одно и то же число раз.

    🔴 Найдено на данных заказчика (30.08.2026) случайно, при подключении
    прироста к карточкам «Главной»: три РАЗНЫХ показателя показали одинаковые
    +3,50 %. Проверка шире дала ответ — в отчётах формы МАХ за 12.08 и 19.08
    все тринадцать показателей выросли ровно в 1,040 и 1,035 раза (разброс в
    пятом знаке — это округление до целых). Живой отчёт за 05.08 ведёт себя
    иначе: от −1,6 % до +35 %. То есть два отчёта, судя по арифметике, получены
    умножением предыдущего, а не собраны из источника.

    По одному файлу такое не видно вовсе, а на дашборде выглядит как обычный
    ровный рост — поэтому правило и нужно.

    Считаем по СУММАМ показателя за выпуск, а не по отдельным ячейкам: у формы
    из шестидесяти отделений отдельная ячейка со значением 7 после умножения
    округляется обратно в 7, и полоса коэффициентов развалилась бы на
    округлении. В сумме по строкам округление незаметно.

    Сравниваем только те ячейки, что есть в ОБОИХ выпусках: появившееся или
    исчезнувшее отделение иначе сдвинуло бы сумму и коэффициент вместе с ней.

    Доли и проценты не берём (то же правило `is_share`, что и в остальных
    проверках): их при таком «пересчёте» обычно оставляют как есть, и одна
    неизменившаяся графа скрыла бы умножение всех остальных.
    """
    from ..dashboards._aggregate import is_share  # локально: иначе цикл импорта

    cur_sums: Dict[str, float] = {}
    prev_sums: Dict[str, float] = {}
    for key, cur in current.items():
        prev = previous.get(key)
        if prev is None or is_share(names.get(key[1], key[1])):
            continue
        cur_sums[key[1]] = cur_sums.get(key[1], 0.0) + cur
        prev_sums[key[1]] = prev_sums.get(key[1], 0.0) + prev

    ratios = {c: cur_sums[c] / prev_sums[c] for c in cur_sums if prev_sums.get(c, 0.0) > 0}
    if len(ratios) < MIN_FIELDS_MULTIPLIED:
        return None

    lo, hi = min(ratios.values()), max(ratios.values())
    # 🔴 Коэффициент 0 — это показатель, просевший до нуля. Такое сплошь и рядом
    # в ежедневном отчёте: услугу за день ни разу не оказали. Делить на него
    # нельзя, но главное — сама гипотеза при этом уже мертва: равномерного
    # умножения на положительное число, при котором одна графа обнулилась, не
    # бывает. Найдено боевой загрузкой: 52 листа из 54 не выпустились вовсе,
    # потому что правило падало ВНУТРИ выпуска.
    if lo <= 0:
        return None
    if (hi - lo) / lo > MULTIPLIED_BAND:
        return None
    ratio = (lo + hi) / 2
    # Коэффициент 1 — это «итоги не сдвинулись», а не признак пересчёта: так
    # выглядит и неделя без движения, и перестановка значений между строками
    # при том же итоге. Полное посимвольное совпадение ловит `same_as_previous`,
    # и второе замечание о том же приучало бы их пролистывать.
    if abs(ratio - 1.0) <= MULTIPLIED_BAND:
        return None

    verb = "выросли" if ratio > 1 else "снизились"
    times = f"{ratio:.3f}".replace(".", ",")
    pct = f"{(ratio - 1.0) * 100:+.2f}".replace(".", ",")
    examples = "; ".join(
        f"«{names.get(c, c)}»: {_fmt(prev_sums[c])} → {_fmt(cur_sums[c])}"
        for c in sorted(ratios, key=lambda c: -prev_sums[c])[:3])
    return {
        "code": "multiplied_by_factor", "count": len(ratios),
        "message": (f"Все {len(ratios)} показателей {verb} ровно в одно и то же число раз "
                    f"(×{times}, то есть {pct} %) — живые данные так себя не ведут. Проверьте, "
                    f"не получен ли отчёт пересчётом предыдущего вместо выгрузки из источника: "
                    f"{examples}"),
    }


def check_release(current: Dict[Key, float], names: Dict[str, str],
                  previous: Optional[Dict[Key, float]] = None,
                  previous_period: Optional[str] = None,
                  partial: bool = False) -> List[dict]:
    """ВСЕ замечания к готовящемуся выпуску: арифметика внутри + сверка с прошлым.

    Единственная точка входа для всех трёх мест, где замечания показываются
    (предпросмотр выпуска, результат выпуска, блок «На что посмотреть»):
    иначе «перед выпуском замечаний не было, а после появились» стало бы
    неизбежным.
    """
    return (check_internal(current, names)
            + compare_with_previous(current, previous or {}, names, previous_period, partial))


def compare_with_previous(
    current: Dict[Key, float],
    previous: Dict[Key, float],
    names: Dict[str, str],
    previous_period: Optional[str] = None,
    partial: bool = False,
) -> List[dict]:
    """Сравнение готовящегося выпуска с предыдущим. Чистая функция, без БД.

    `partial` — сравнивается НЕ вся форма, а только часть строк (так бывает на
    дашборде, где действует RLS по строкам). Тогда «все данные совпадают»
    означает «все ДОСТУПНЫЕ вам строки»: без этой оговорки человек с одной
    разрешённой строкой решил бы, что не обновилась вся форма.
    """
    warnings: List[dict] = []
    if not previous:
        return warnings

    period_txt = f" за {previous_period}" if previous_period else ""

    # ── 1. Накопительный итог не может уменьшиться ────────────────────────────
    drops: List[str] = []
    for key, cur in current.items():
        prev = previous.get(key)
        if prev is None or classify_slice(names.get(key[1], "")) != "cumulative":
            continue
        if cur < prev:
            drops.append(f"«{names.get(key[1], key[1])}» в строке «{key[0]}»: было {_fmt(prev)}, стало {_fmt(cur)}")
    if drops:
        warnings.append({
            "code": "cumulative_drop", "count": len(drops),
            "message": ("Накопительный итог уменьшился — так не бывает, если это тот же показатель: "
                        + "; ".join(drops[:5])),
        })

    # ── 3. Данные совпадают с прошлой неделей ────────────────────────────────
    # Считаем ПОСТРОЧНО, а не по выпуску целиком: у заказчика совпала ровно одна
    # строка, а в форме была ещё одна — сравнение «весь файл целиком» такой
    # случай пропустило бы.
    rows_now = {k[0] for k in current}
    same_rows = []
    for row in sorted(rows_now):
        cells = {k[1]: v for k, v in current.items() if k[0] == row}
        prev_cells = {k[1]: v for k, v in previous.items() if k[0] == row}
        if not cells or not prev_cells:
            continue
        if set(cells) == set(prev_cells) and all(prev_cells[f] == v for f, v in cells.items()):
            same_rows.append(row)
    if same_rows:
        whole = len(same_rows) == len(rows_now)
        all_txt = ("Все доступные вам строки совпадают с прошлым выпуском" if partial
                   else "Все данные совпадают с прошлым выпуском")
        head = (all_txt if whole
                else f"Совпадают с прошлым выпуском строки: {', '.join(f'«{r}»' for r in same_rows[:5])}")
        warnings.append({
            "code": "same_as_previous", "count": len(same_rows),
            "message": (f"{head}{period_txt} — проверьте, не перенесены ли цифры прошлой недели "
                        "без обновления."),
        })

    # ── 4. Плановое значение не должно меняться от отчёта к отчёту ───────────
    # План задаётся на СРОК («до 1 сентября»), поэтому в еженедельной форме он
    # обязан повторяться неизменным. Если он растёт каждую неделю — в графу
    # «План» почти наверняка попадает факт из другого источника, и тогда
    # «выполнение плана» на дашборде считается сам с собой. Найдено осмотром
    # данных заказчика: план по записавшимся шёл 38 992 → 38 992 → 40 552 →
    # 41 971 при неизменном сроке.
    moved: List[str] = []
    for key, cur in current.items():
        prev = previous.get(key)
        if prev is None or prev == cur:
            continue
        name = names.get(key[1], "")
        if _split_name(name).get("role") != "plan":
            continue
        moved.append(f"«{name}» в строке «{key[0]}»: было {_fmt(prev)}, стало {_fmt(cur)}")
    if moved:
        warnings.append({
            "code": "plan_changed", "count": len(moved),
            "message": ("Плановое значение изменилось с прошлого отчёта — план задаётся на срок и "
                        "меняться не должен; проверьте, не попал ли в графу «План» факт: "
                        + "; ".join(moved[:5])),
        })

    # ── 5. Все показатели изменились в одно и то же число раз ───────────────
    mult = _check_multiplied(current, previous, names)
    if mult:
        warnings.append(mult)

    return warnings


def values_from_rows(rows: Sequence[Sequence[str]], fields: Sequence[dict],
                     label_col: Optional[int]) -> Dict[Key, float]:
    """Числовые значения размеченной таблицы в виде {(строка, поле): число}."""
    from . import analyze

    out: Dict[Key, float] = {}
    for row in rows:
        label = str(row[label_col]) if label_col is not None and label_col < len(row) else ""
        for f in fields:
            if f.get("is_row_label") or f.get("data_type") != "number":
                continue
            ci = f["column_index"]
            num = analyze.parse_number(row[ci] if ci < len(row) else "")
            if num is not None:
                out[(label, f["field_code"])] = num
    return out


async def previous_release_values(conn, org_id, code: str, before_period) -> tuple:
    """Значения последнего активного выпуска этого кода ДО указанного периода.

    Сравнивать надо с предыдущей неделей, а не с выпуском за тот же период:
    повторный выпуск за ту же дату — это исправление, и совпадение с ним
    ожидаемо. Возвращает ({(строка, поле): число}, дата выпуска-источника).
    """
    rel = await conn.fetchrow(
        "select id, reporting_period_start from dataset_releases "
        "where organization_id=$1 and code=$2 and status <> 'superseded' "
        "  and ($3::text is null or reporting_period_start < $3::text::date) "
        "order by reporting_period_start desc nulls last, created_at desc limit 1",
        org_id, code, str(before_period) if before_period else None)
    if rel is None:
        return {}, None
    rows = await conn.fetch(
        "select row_label, canonical_field_code, value_number from dataset_values "
        "where dataset_release_id=$1 and value_number is not null", rel["id"])
    values = {(r["row_label"] or "", r["canonical_field_code"]): float(r["value_number"]) for r in rows}
    period = rel["reporting_period_start"]
    return values, (period.strftime("%d.%m.%Y") if period else None)
