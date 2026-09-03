"""Проверки качества данных: сверка готовящегося выпуска с прошлой неделей.

Главный случай — настоящий, из практики заказчика (05.08.2026): строка
«Донецкая Народная Республика» в новом отчёте совпала с отчётом за 29.07
посимвольно. Данные неделю не обновляли, система приняла их молча, и на
дашборде они выглядели свежими. Заметить такое по одному файлу нельзя —
только сравнением с предыдущим выпуском.

Проверки НЕ блокируют выпуск (решение за человеком, выпуск обратим), поэтому
тесты требуют именно предупреждений, а не отказов.
"""
import pytest

from app.modules.ingestion import quality

NAMES = {
    "obr_total": "Количество обращений · Факт · нарастающим итогом",
    "obr_week": "Количество обращений · Факт · за отчётную неделю",
    "uved_total": "Количество уведомлений · Факт · нарастающим итогом",
}


def test_row_copied_from_previous_week_is_flagged():
    """Строка не изменилась за неделю — самый дорогой случай, ловим его."""
    prev = {("ДНР", "obr_total"): 891651.0, ("ДНР", "uved_total"): 108584.0,
            ("Мариуполь", "obr_total"): 1000.0, ("Мариуполь", "uved_total"): 500.0}
    cur = {("ДНР", "obr_total"): 891651.0, ("ДНР", "uved_total"): 108584.0,   # не обновили
           ("Мариуполь", "obr_total"): 1200.0, ("Мариуполь", "uved_total"): 600.0}

    w = quality.compare_with_previous(cur, prev, NAMES, "29.07.2026")
    same = [x for x in w if x["code"] == "same_as_previous"]
    assert same, w
    assert "ДНР" in same[0]["message"]
    assert "Мариуполь" not in same[0]["message"], "изменившаяся строка не должна попадать в замечание"
    assert "29.07.2026" in same[0]["message"]


def test_all_rows_identical_says_so_plainly():
    prev = {("ДНР", "obr_total"): 100.0}
    w = quality.compare_with_previous(dict(prev), prev, NAMES, "29.07.2026")
    assert any("Все данные совпадают" in x["message"] for x in w), w


def test_cumulative_total_cannot_decrease():
    """Накопительный итог уменьшился — либо ошибка в форме, либо не тот показатель."""
    prev = {("ДНР", "obr_total"): 891651.0}
    cur = {("ДНР", "obr_total"): 800000.0}
    w = quality.compare_with_previous(cur, prev, NAMES, "29.07.2026")
    drop = [x for x in w if x["code"] == "cumulative_drop"]
    assert drop, w
    assert "891 651" in drop[0]["message"] and "800 000" in drop[0]["message"]


def test_weekly_slice_not_flagged_when_it_drops():
    """Значение ЗА НЕДЕЛЮ падать может — это срез, а не накопление."""
    prev = {("ДНР", "obr_week"): 50000.0, ("ДНР", "obr_total"): 891651.0}
    cur = {("ДНР", "obr_week"): 30000.0, ("ДНР", "obr_total"): 929825.0}
    w = quality.compare_with_previous(cur, prev, NAMES, "29.07.2026")
    assert not [x for x in w if x["code"] == "cumulative_drop"], w


def test_weekly_cannot_exceed_cumulative():
    """За неделю больше, чем накопленным итогом — графы перепутаны местами.

    Правило ПЕРЕЕХАЛО из сверки с прошлой неделей во внутренние проверки: ему
    прошлый выпуск не нужен, а живя в сверке оно молчало на первом файле формы
    — то есть ровно там, где ошибку ещё никто не мог заметить. Тест проверяет
    обе стороны: правило работает БЕЗ прошлого выпуска и доезжает до общей
    `check_release`.
    """
    cur = {("ДНР", "obr_total"): 1000.0, ("ДНР", "obr_week"): 5000.0}
    over = [x for x in quality.check_internal(cur, NAMES) if x["code"] == "weekly_over_total"]
    assert over, "первый файл формы тоже должен проверяться"
    assert "5 000" in over[0]["message"]
    assert any(x["code"] == "weekly_over_total"
               for x in quality.check_release(cur, NAMES, {("ДНР", "obr_total"): 100.0}, "29.07.2026"))


def test_first_release_has_nothing_to_compare_with():
    """Сверке с прошлым сравнивать не с чем — но молчит ТОЛЬКО она."""
    assert quality.compare_with_previous({("ДНР", "obr_total"): 1.0}, {}, NAMES, None) == []
    # А внутренняя арифметика на первом файле обязана работать.
    cur = {("ДНР", "obr_total"): 10.0, ("ДНР", "obr_week"): 99.0}
    assert quality.check_release(cur, NAMES) , "на первом файле проверки не должны молчать"


def test_slice_classification():
    assert quality.classify_slice(NAMES["obr_total"]) == "cumulative"
    assert quality.classify_slice(NAMES["obr_week"]) == "weekly"
    # Месячный накопительный итог законно падает при смене месяца — не сравниваем.
    assert quality.classify_slice("Обращения · Факт · нарастающим итогом (текущий месяц)") == "other"


def test_values_from_rows_takes_only_numeric_fields():
    fields = [
        {"column_index": 0, "field_code": "subj", "field_name": "Субъект", "data_type": "text", "is_row_label": True},
        {"column_index": 1, "field_code": "obr_total", "field_name": NAMES["obr_total"], "data_type": "number"},
        {"column_index": 2, "field_code": "note", "field_name": "Примечание", "data_type": "text"},
    ]
    got = quality.values_from_rows([["ДНР", "1 234", "текст"]], fields, 0)
    assert got == {("ДНР", "obr_total"): 1234.0}


@pytest.mark.asyncio(loop_scope="session")
async def test_quality_check_endpoint_sees_copied_week(client, admin_headers, monkeypatch):
    """Сквозной путь: тот же файл за новую неделю → замечание ДО выпуска."""
    import io

    from app import db
    from app.modules.documents import storage
    from app.modules.ingestion import service

    def _xlsx(value: int) -> bytes:
        from openpyxl import Workbook
        wb = Workbook(); ws = wb.active
        ws.append(["Субъект", "Количество обращений · Факт · нарастающим итогом"])
        ws.append(["ДНР", value])
        buf = io.BytesIO(); wb.save(buf); return buf.getvalue()

    r = await client.post("/objects", headers=admin_headers, json={"name": "ztest_qual_obj"})
    oid = r.json()["id"]
    r = await client.post(f"/objects/{oid}/folders", headers=admin_headers, json={"name": "ztest_qual_folder"})
    fid = r.json()["id"]

    async def upload(content, period):
        monkeypatch.setattr(storage, "put_object", lambda n, d, c: f"documents/{n}")
        monkeypatch.setattr(storage, "get_object", lambda p: content)
        # force=true: в этом сценарии тот же файл заливается за новую неделю
        # НАМЕРЕННО — проверяется сверка строк с прошлым выпуском. Побайтовый
        # дубль ловится раньше (п. 7) и требует подтверждения человека; две
        # защиты дополняют друг друга, поэтому здесь подтверждение выдаём сразу.
        rr = await client.post(
            f"/folders/{fid}/documents", headers=admin_headers,
            files={"file": (f"q_{period}.xlsx", content,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"reporting_period_start": period, "force": "true"})
        job_id = rr.json()["extraction_job_id"]
        await service.run_extraction(job_id)
        return (await client.get(f"/extraction-jobs/{job_id}", headers=admin_headers)).json()

    def body(job, period):
        t = job["tables"][0]
        return {
            "table_id": t["id"], "code": "zqual_code", "name": f"Форма {period}",
            "reporting_period_start": period,
            "fields": [
                {"column_index": 0, "field_code": "subj", "field_name": "Субъект",
                 "data_type": "text", "is_row_label": True},
                {"column_index": 1, "field_code": "obr_total",
                 "field_name": "Количество обращений · Факт · нарастающим итогом",
                 "data_type": "number", "is_row_label": False},
            ],
            "layout": {"data_rect": [0, 0, 1, 1], "header_rows": 1,
                       "orientation": "columns", "skip_rows": []},
        }

    try:
        job1 = await upload(_xlsx(891651), "2026-07-22")
        r = await client.post(f"/extraction-jobs/{job1['job_id']}/release",
                              headers=admin_headers, json=body(job1, "2026-07-22"))
        assert r.status_code == 201, r.text

        # Та же цифра за следующую неделю — данные не обновили.
        job2 = await upload(_xlsx(891651), "2026-07-29")
        r = await client.post(f"/extraction-jobs/{job2['job_id']}/quality-check",
                              headers=admin_headers, json=body(job2, "2026-07-29"))
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is False
        assert any(w["code"] == "same_as_previous" for w in r.json()["warnings"]), r.json()

        # То же замечание приезжает и в результате выпуска — расхождения быть не может.
        r = await client.post(f"/extraction-jobs/{job2['job_id']}/release",
                              headers=admin_headers, json=body(job2, "2026-07-29"))
        assert r.status_code == 201, r.text
        assert any(w["code"] == "same_as_previous" for w in r.json()["validation"]["warnings"])
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from dataset_values where dataset_release_id in "
                               "(select id from dataset_releases where object_id=$1::uuid)", oid)
            await conn.execute("delete from dataset_release_fields where dataset_release_id in "
                               "(select id from dataset_releases where object_id=$1::uuid)", oid)
            await conn.execute("delete from object_layout_templates where object_id=$1::uuid", oid)
            await conn.execute("delete from dataset_releases where object_id=$1::uuid", oid)
            await conn.execute("delete from canonical_fields where object_id=$1::uuid", oid)
            await conn.execute("delete from extraction_jobs where document_version_id in "
                               "(select dv.id from document_versions dv join documents d on d.id=dv.document_id "
                               " where d.folder_id=$1::uuid)", fid)
            await conn.execute("delete from document_versions where document_id in "
                               "(select id from documents where folder_id=$1::uuid)", fid)
            await conn.execute("delete from documents where folder_id=$1::uuid", fid)
            await conn.execute("delete from folders where id=$1::uuid", fid)
            await conn.execute("delete from objects where id=$1::uuid", oid)


def test_plan_value_must_not_move_between_reports():
    """План задаётся на СРОК и меняться от отчёта к отчёту не должен.

    Найдено осмотром данных заказчика: план по записавшимся шёл
    38 992 → 38 992 → 40 552 → 41 971 при неизменном сроке «до 1 сентября».
    Так выглядит факт, попавший в графу «План», — и тогда «выполнение плана»
    на дашборде считается сам с собой.
    """
    names = {"plan": "Записались · План (до 1 сентября 2026 г.)",
             "fact": "Записались · Факт · нарастающим итогом"}
    prev = {("ДНР", "plan"): 38992.0, ("ДНР", "fact"): 250000.0}
    cur = {("ДНР", "plan"): 41971.0, ("ДНР", "fact"): 275694.0}
    codes = {w["code"] for w in quality.compare_with_previous(cur, prev, names)}
    assert "plan_changed" in codes, "изменение плана обязано попасть в замечания"

    # Факт растёт — это норма, о нём правило молчит.
    same_plan = {("ДНР", "plan"): 38992.0, ("ДНР", "fact"): 275694.0}
    codes2 = {w["code"] for w in quality.compare_with_previous(same_plan, prev, names)}
    assert "plan_changed" not in codes2

    # Текст называет и показатель, и обе величины: без них замечание не проверить.
    msg = next(w["message"] for w in quality.compare_with_previous(cur, prev, names)
               if w["code"] == "plan_changed")
    assert "38 992" in msg and "41 971" in msg and "Записались" in msg


# ── Отчёт, полученный умножением предыдущего ─────────────────────────────────
#
# Числа во всех тестах ниже — НАСТОЯЩИЕ, из формы «Внедрение сервиса МАХ»
# заказчика. Синтетика тут была бы слабее: правило целиком про то, отличает ли
# оно живой отчёт от пересчитанного, а это вопрос к реальному разбросу, а не к
# придуманному.

MAX_NAMES = {
    "otpr": "Количество отправленных уведомлений · Факт · нарастающим итогом",
    "obr": "Количество обращений за результатом · Факт · нарастающим итогом",
    "dost": "Количество успешно доставленных уведомлений · Факт · нарастающим итогом",
    "dost_m": "Количество успешно доставленных уведомлений · Факт · нарастающим итогом (текущий месяц)",
    "otpr_m": "Количество отправленных уведомлений · Факт · нарастающим итогом (текущий месяц)",
    "zap": "Количество пользователей, записавшихся на посещение МФЦ · Факт · за отчётную неделю",
}


def _cells(values: dict, row: str = "ДНР") -> dict:
    return {(row, code): float(v) for code, v in values.items()}


# Отчёты за 12.08 и 19.08.2026: все тринадцать показателей выросли ровно
# в 1,035 раза. Разброс коэффициентов — в пятом знаке, это округление до целых.
MULTIPLIED_PREV = {"otpr": 2451769, "obr": 967018, "dost": 911538,
                   "dost_m": 486618, "otpr_m": 449586, "zap": 266371}
MULTIPLIED_CUR = {"otpr": 2537581, "obr": 1000864, "dost": 943442,
                  "dost_m": 503650, "otpr_m": 465322, "zap": 275694}

# Отчёт за 05.08.2026 против 22.07: живые данные, каждый показатель менялся
# по-своему — от «не изменился вовсе» до +30 %.
LIVE_PREV = {"otpr": 2257155, "obr": 891651, "dost": 847714,
             "dost_m": 467902, "otpr_m": 331979, "zap": 249048}
LIVE_CUR = {"otpr": 2357470, "obr": 929825, "dost": 876479,
            "dost_m": 467902, "otpr_m": 432294, "zap": 256126}


def test_report_multiplied_by_single_factor_is_flagged():
    """Все показатели изменились в одно и то же число раз — так не бывает.

    Найдено случайно 30.08.2026: три РАЗНЫХ показателя на «Главной» показали
    одинаковые +3,50 %. По одному файлу такое не видно вовсе, а на дашборде
    выглядит как обычный ровный рост.
    """
    w = quality.compare_with_previous(_cells(MULTIPLIED_CUR), _cells(MULTIPLIED_PREV),
                                      MAX_NAMES, "12.08.2026")
    mult = [x for x in w if x["code"] == "multiplied_by_factor"]
    assert mult, w
    msg = mult[0]["message"]
    # Замечание обязано назвать коэффициент: без него человеку нечего проверять
    # в исходном файле.
    assert "×1,035" in msg and "+3,50 %" in msg, msg
    assert "2 451 769" in msg and "2 537 581" in msg, msg
    assert mult[0]["count"] == len(MULTIPLIED_CUR)


def test_live_report_with_varied_growth_is_not_flagged():
    """Живой отчёт правило пропускает молча — иначе им перестанут пользоваться."""
    codes = {x["code"] for x in quality.compare_with_previous(
        _cells(LIVE_CUR), _cells(LIVE_PREV), MAX_NAMES, "22.07.2026")}
    assert "multiplied_by_factor" not in codes


def test_needs_enough_indicators_to_be_confident():
    """На двух-трёх показателях совпадение коэффициента ещё может быть случайным.

    Правило либо срабатывает уверенно, либо молчит: на мелкой форме оно молчит
    даже при точном совпадении.
    """
    few_prev = {("ДНР", c): float(v) for c, v in list(MULTIPLIED_PREV.items())[:3]}
    few_cur = {("ДНР", c): float(v) for c, v in list(MULTIPLIED_CUR.items())[:3]}
    assert not [x for x in quality.compare_with_previous(few_cur, few_prev, MAX_NAMES)
                if x["code"] == "multiplied_by_factor"]

    four_prev = {("ДНР", c): float(v) for c, v in list(MULTIPLIED_PREV.items())[:4]}
    four_cur = {("ДНР", c): float(v) for c, v in list(MULTIPLIED_CUR.items())[:4]}
    assert [x for x in quality.compare_with_previous(four_cur, four_prev, MAX_NAMES)
            if x["code"] == "multiplied_by_factor"]


def test_unchanged_report_is_not_reported_twice():
    """Коэффициент 1 — это «перенесли прошлую неделю», и об этом говорит
    ДРУГОЕ правило. Два замечания об одном и том же приучают их пролистывать."""
    same = _cells(MULTIPLIED_PREV)
    codes = {x["code"] for x in quality.compare_with_previous(dict(same), same, MAX_NAMES)}
    assert "same_as_previous" in codes, "случай не должен пропасть вовсе"
    assert "multiplied_by_factor" not in codes


def test_percent_column_does_not_hide_multiplication():
    """Процентная графа при пересчёте обычно остаётся прежней.

    Если считать её наравне с количествами, одна неизменившаяся графа развалит
    полосу коэффициентов и скроет умножение всех остальных.
    """
    names = dict(MAX_NAMES, dolya="Доля доставленных уведомлений, %")
    prev = {**_cells(MULTIPLIED_PREV), ("ДНР", "dolya"): 37.18}
    cur = {**_cells(MULTIPLIED_CUR), ("ДНР", "dolya"): 37.18}
    assert [x for x in quality.compare_with_previous(cur, prev, names)
            if x["code"] == "multiplied_by_factor"]


def test_new_row_does_not_distort_the_factor():
    """Появившееся отделение не должно сбивать коэффициент.

    Сравниваем только ячейки, которые есть в ОБОИХ выпусках: иначе новая строка
    вошла бы в сумму текущего выпуска и коэффициент по каждому показателю уехал
    бы по-своему — умножение осталось бы незамеченным.
    """
    prev = {("Донецк", c): float(v) for c, v in MULTIPLIED_PREV.items()}
    prev.update({("Макеевка", c): float(v) / 3 for c, v in MULTIPLIED_PREV.items()})
    cur = {("Донецк", c): float(v) for c, v in MULTIPLIED_CUR.items()}
    cur.update({("Макеевка", c): float(v) / 3 for c, v in MULTIPLIED_CUR.items()})
    # Отделение открылось на этой неделе: своей истории у него нет, а цифры
    # по показателям у него разные — именно они и сбили бы полосу.
    cur.update({("Горловка", c): float(v) * k
                for k, (c, v) in enumerate(MULTIPLIED_CUR.items(), start=1)})

    assert [x for x in quality.compare_with_previous(cur, prev, MAX_NAMES)
            if x["code"] == "multiplied_by_factor"]


def test_indicator_dropping_to_zero_does_not_break_the_rule():
    """🔴 Показатель, просевший до нуля, не должен ронять правило — и выпуск.

    Найдено боевой загрузкой ежедневного отчёта РЦО: услугу за день ни разу не
    оказали, коэффициент её роста стал нулём, а правило делило на минимальный
    коэффициент. Падало оно ВНУТРИ выпуска, поэтому не выпустилось 52 листа из
    54 — проверка, которая по замыслу только советует, отменяла саму работу.

    По существу гипотеза при нуле и так мертва: равномерного умножения на
    положительное число, при котором одна графа обнулилась, не бывает.
    """
    names = {f"f{i}": f"Услуга {i} · Факт · нарастающим итогом" for i in range(5)}
    prev = {("Отделение", f"f{i}"): 100.0 for i in range(5)}
    cur = {("Отделение", f"f{i}"): 104.0 for i in range(5)}
    cur[("Отделение", "f0")] = 0.0          # услугу сегодня не оказывали

    w = quality.compare_with_previous(cur, prev, names, "01.07.2026")
    assert not [x for x in w if x["code"] == "multiplied_by_factor"]

    # А без обнулившейся графы правило по-прежнему срабатывает: защита не
    # должна была отключить его вовсе.
    cur[("Отделение", "f0")] = 104.0
    assert [x for x in quality.compare_with_previous(cur, prev, names, "01.07.2026")
            if x["code"] == "multiplied_by_factor"]

@pytest.mark.asyncio(loop_scope="session")
async def test_broken_rule_does_not_cancel_the_release(seed_dataset, monkeypatch):
    """🔴 Сломавшаяся проверка обязана промолчать, а не сорвать выпуск.

    Это страховка ВТОРОГО слоя. Корневую причину (деление на ноль) закрывает
    тест выше, но правил в модуле пять и будут новые: проверки по замыслу
    СОВЕТУЮТ, значит ошибка в подсказке не вправе отменять саму работу. Ровно
    это и случилось при загрузке ежедневного отчёта РЦО — 52 выпуска из 54 не
    состоялись из-за сбоя в подсказке.

    Бьём по `mapping.quality_warnings`, а не по `check_release`: страховка живёт
    именно там, и прежние тесты проходили мимо неё.
    """
    from app import db
    from app.modules.ingestion import mapping, quality

    fields = [
        {"column_index": 0, "field_code": "office", "field_name": "Отделение",
         "data_type": "text", "is_row_label": True},
        {"column_index": 1, "field_code": "plan", "field_name": "План · нарастающим итогом",
         "data_type": "number", "is_row_label": False},
    ]
    rows = [["Донецк", "100"]]

    def boom(*_a, **_kw):
        raise ZeroDivisionError("float division by zero")

    monkeypatch.setattr(quality, "check_release", boom)
    async with db.acquire() as conn:
        org = await conn.fetchval("select id from organizations limit 1")
        broken = await mapping.quality_warnings(
            conn, org, code=seed_dataset["code"], period=None,
            rows=rows, fields=fields, label_col=0)
    assert broken == [], "выпуск продолжается — замечаний просто нет"

    # А с исправными правилами проверки по-прежнему работают: страховка не
    # должна была отключить их вовсе.
    monkeypatch.undo()
    async with db.acquire() as conn:
        org = await conn.fetchval("select id from organizations limit 1")
        ok = await mapping.quality_warnings(
            conn, org, code=seed_dataset["code"], period=None,
            rows=rows, fields=fields, label_col=0)
    assert isinstance(ok, list)

def test_almost_empty_release_is_named():
    """🔴 Лист-заготовка ещё не заполненного дня.

    Числа НАСТОЯЩИЕ, из ежедневного отчёта РЦО: 186 заполненных клеток против
    20 088 накануне — 0,92 %. Данные при этом верные, день просто не наступил.
    Но виджет читает ПОСЛЕДНИЙ выпуск, поэтому дашборд открывался пустым, и
    человек видел нули там, где ждал цифры.
    """
    prev = {(f"Отделение {i}", f"f{j}"): 1.0 for i in range(62) for j in range(324)}
    cur = {(f"Отделение {i}", "f0"): 0.0 for i in range(186)}
    w = quality.compare_with_previous(cur, prev, {}, "31.08.2026")
    empty = [x for x in w if x["code"] == "almost_empty"]
    assert empty, "почти пустой выпуск обязан быть назван"
    # Запятая, а не точка: в проекте принята русская запись дробей, и тест не
    # должен подменять её сам — иначе он пропустит именно то, что проверяет.
    assert "186" in empty[0]["message"] and "0,9 %" in empty[0]["message"]


def test_short_working_day_is_not_called_empty():
    """А короткий день — не пустой, и правило о нём молчит.

    Замер по 53 парам выпусков РЦО: рабочий день даёт 100 % заполненных клеток
    от предыдущего, суббота — около 50 %, второе снизу значение по всей истории
    45,79 %. Сработай правило на них, его приучились бы пролистывать.
    """
    prev = {(f"Отделение {i}", f"f{j}"): 1.0 for i in range(62) for j in range(324)}
    half = {k: v for i, (k, v) in enumerate(prev.items()) if i % 2 == 0}   # 50 %
    assert not [x for x in quality.compare_with_previous(half, prev, {}, "28.08.2026")
                if x["code"] == "almost_empty"]


def test_tiny_form_does_not_trigger_the_rule():
    """На мелкой форме доля скачет от одной ячейки — правило молчит."""
    prev = {("Строка", f"f{j}"): 1.0 for j in range(10)}
    cur = {("Строка", "f0"): 1.0}
    assert not [x for x in quality.compare_with_previous(cur, prev, {}, "01.07.2026")
                if x["code"] == "almost_empty"]

