"""Памятка расчёта страницы: одни и те же справочные запросы — один раз.

Замер после устранения главного N+1: на «Обзоре» РЦО оставалось 261 обращение к
базе, из них 77 — «какой выпуск активен» и 49 — «как называется этот столбец».
Оба запроса справочные: в пределах ОДНОГО расчёта страницы ответ на них не
меняется, а задаются они на каждое поле каждого виджета.

🔴 Главный риск здесь не производительность, а протечка: ключ обязан включать
организацию и дату, иначе виджет покажет данные чужой организации — и выглядеть
это будет совершенно правдоподобно. Поэтому тесты в этом файле — прежде всего
про изоляцию, а не про скорость.
"""
from __future__ import annotations

import pytest

from app.modules.dashboards import _pagecalc as pc

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_bez_pamyatki_nichego_ne_keshiruetsya():
    """Вне расчёта страницы памятки нет: одиночный виджет и выгрузка идут в базу.

    Кэш, живущий дольше запроса, — источник данных «из прошлого раза».
    """
    calls = []

    async def load():
        calls.append(1)
        return "значение"

    assert await pc.memo(("k",), load) == "значение"
    assert await pc.memo(("k",), load) == "значение"
    assert len(calls) == 2, "вне расчёта страницы ответы кэшироваться не должны"


async def test_vnutri_rascheta_zapros_odin():
    calls = []

    async def load():
        calls.append(1)
        return 42

    with pc.page_scope():
        assert await pc.memo(("k",), load) == 42
        assert await pc.memo(("k",), load) == 42
    assert len(calls) == 1, f"справочный запрос выполнен {len(calls)} раза вместо одного"


async def test_raznye_klyuchi_ne_smeshivayutsya():
    """🔴 Организация и дата входят в ключ: иначе виджет покажет чужие данные."""
    async def load_a():
        return "организация А"

    async def load_b():
        return "организация Б"

    with pc.page_scope():
        a = await pc.memo(("org-a", "code", None), load_a)
        b = await pc.memo(("org-b", "code", None), load_b)
    assert (a, b) == ("организация А", "организация Б"), "ответы перепутались между ключами"


async def test_pamyatka_ne_perezhivaet_raschet():
    """После расчёта страницы памятка обязана исчезнуть."""
    calls = []

    async def load():
        calls.append(1)
        return "x"

    with pc.page_scope():
        await pc.memo(("k",), load)
    with pc.page_scope():
        await pc.memo(("k",), load)
    assert len(calls) == 2, "значение утекло из одного расчёта страницы в другой"


async def test_oshibka_ne_zapominaetsya():
    """Сбой не должен закрепиться на весь расчёт: следующий виджет попробует снова."""
    calls = []

    async def failing():
        calls.append(1)
        raise RuntimeError("база недоступна")

    with pc.page_scope():
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await pc.memo(("k",), failing)
    assert len(calls) == 2, "ошибка закэширована — виджеты ниже её унаследуют"


async def test_none_eto_tozhe_otvet():
    """None («выпуска нет») — полноценный ответ, а не повод спрашивать снова."""
    calls = []

    async def load_none():
        calls.append(1)
        return None

    with pc.page_scope():
        assert await pc.memo(("k",), load_none) is None
        assert await pc.memo(("k",), load_none) is None
    assert len(calls) == 1, "None не запомнился — запрос повторяется на каждом виджете"
