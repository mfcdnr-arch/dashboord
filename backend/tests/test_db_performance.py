"""Индексы и пороги автоанализа для таблиц, которые растут пачками.

Почему это стоит проверять тестом, а не «один раз настроили». Обе вещи —
невидимые: без индекса запрос работает, просто читает всю таблицу, а устаревшая
статистика не ломает ответ, она делает план плохим. Заметить такое можно только
замером, а замеряют редко — значит регрессия проживёт долго.

Замеры на живых данных стенда, от которых отталкивались:
  • `extracted_columns` (58 609 строк) читалась последовательно — 3 255 буферов
    на каждый запрос колонок таблицы, то есть при каждом открытии разметки;
  • `dataset_values` (1,2 млн строк) анализировалась только после 122 034
    изменений, а один отчёт РЦО добавляет ~21 600 значений: статистика
    обновлялась примерно раз в шесть отчётов, и между ними планировщик работал
    вслепую.
"""
from __future__ import annotations

import pytest

from app import db

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_kolonki_tablitsy_ischutsya_po_indeksu():
    """🔴 Без индекса разметка читает всю таблицу колонок при каждом открытии."""
    async with db.acquire() as conn:
        idx = await conn.fetch(
            "select indexdef from pg_indexes where tablename='extracted_columns'")
        defs = " ".join(r["indexdef"] for r in idx)
        assert "extracted_table_id" in defs, \
            "нет индекса по extracted_table_id — колонки ищутся последовательным сканированием"


async def test_plan_zaprosa_kolonok_ne_skaniruet_tablitsu():
    """Проверяем не наличие индекса, а то, что планировщик им пользуется."""
    async with db.acquire() as conn:
        plan = await conn.fetch(
            "explain select id, column_index from extracted_columns "
            "where extracted_table_id='00000000-0000-0000-0000-000000000000'::uuid order by column_index")
        text = " ".join(r["QUERY PLAN"] for r in plan)
        assert "Seq Scan" not in text, f"таблица колонок всё ещё читается целиком:\n{text}"


async def test_krupnye_tablitsy_analiziruyutsya_chasche_umolchaniya():
    """Порог автоанализа понижен там, где данные приходят большими пачками.

    Умолчание 10 % таблицы рассчитано на равномерный поток мелких правок. У нас
    данные приходят отчётами по десятки тысяч строк, и при таком пороге
    статистика отстаёт на несколько отчётов.
    """
    async with db.acquire() as conn:
        rows = await conn.fetch(
            "select c.relname, c.reloptions from pg_class c "
            "join pg_namespace n on n.oid=c.relnamespace "
            "where n.nspname='public' and c.relname in ('dataset_values','audit_log')")
        opts = {r["relname"]: " ".join(r["reloptions"] or []) for r in rows}
        for table in ("dataset_values", "audit_log"):
            assert table in opts, f"таблица {table} не найдена"
            assert "autovacuum_analyze_scale_factor" in opts[table], \
                f"у {table} порог автоанализа оставлен по умолчанию (10 % таблицы) — " \
                f"статистика будет отставать на несколько отчётов"


async def test_statistika_po_znacheniyam_sobrana():
    """Планировщик должен опираться на собранную статистику, а не на догадки."""
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "select last_analyze, last_autoanalyze, n_live_tup from pg_stat_user_tables "
            "where relname='dataset_values'")
        assert row is not None
        if row["n_live_tup"] and row["n_live_tup"] > 1000:
            assert row["last_analyze"] or row["last_autoanalyze"], \
                "статистика по dataset_values не собиралась ни разу"
