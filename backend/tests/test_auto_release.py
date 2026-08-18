"""Авто-выпуск данных при совпадении структуры (решение заказчика 17.08).

Правило «автомат готовит — выпускает человек» (15.08) остаётся для всего, что
хоть чем-то отличается. Автоматически выпускаем ТОЛЬКО когда совпало всё сразу:
включена автоподготовка папки, отпечаток структуры совпал с прошлым выпуском,
за эту отчётную дату выпуска ещё нет, и проверки качества молчат.

Здесь закрепляются именно ЗАПРЕТЫ: цена ошибки — кривой файл, молча попавший
в цифры руководителя.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app.modules.ingestion import service as ing


async def test_auto_release_skips_when_no_template_match(monkeypatch):
    """Форма отличается — выпуска нет. Чужая разметка дала бы неверные цифры."""
    calls = []

    class FakeConn:
        async def fetchrow(self, sql, *args):
            if "extraction_jobs ej" in sql:
                return {"id": "j", "template_match": "structure_differs",
                        "document_version_id": "v", "reporting_period_start": "2026-08-12",
                        "original_filename": "f.xlsx", "auto_prepare": True, "auto_release": True,
                        "folder_name": "Папка", "organization_id": "o"}
            return None
        async def fetch(self, *a, **k):
            return []
        async def fetchval(self, *a, **k):
            return None

    from app.modules.ingestion import mapping
    monkeypatch.setattr(mapping, "build_release",
                        lambda *a, **k: calls.append(k))
    await ing._auto_release(FakeConn(), "j")
    assert not calls, "при несовпадении структуры выпускать нельзя"


async def test_auto_release_skips_when_folder_auto_prepare_off(monkeypatch):
    """Папка «на хранение» (автоподготовка выключена) в дашборды не попадает."""
    calls = []

    class FakeConn:
        async def fetchrow(self, sql, *args):
            if "extraction_jobs ej" in sql:
                return {"id": "j", "template_match": "exact", "document_version_id": "v",
                        "reporting_period_start": "2026-08-12", "original_filename": "f.xlsx",
                        "auto_prepare": False, "auto_release": True,
                        "folder_name": "Папка", "organization_id": "o"}
            return None
        async def fetch(self, *a, **k):
            return []
        async def fetchval(self, *a, **k):
            return None

    from app.modules.ingestion import mapping
    monkeypatch.setattr(mapping, "build_release", lambda *a, **k: calls.append(k))
    await ing._auto_release(FakeConn(), "j")
    assert not calls


async def test_auto_release_skips_without_reporting_date(monkeypatch):
    """Без отчётной даты выпускать некуда: она — ключ ряда недель."""
    calls = []

    class FakeConn:
        async def fetchrow(self, sql, *args):
            if "extraction_jobs ej" in sql:
                return {"id": "j", "template_match": "exact", "document_version_id": "v",
                        "reporting_period_start": None, "original_filename": "f.xlsx",
                        "auto_prepare": True, "auto_release": True,
                        "folder_name": "Папка", "organization_id": "o"}
            return None
        async def fetch(self, *a, **k):
            return []
        async def fetchval(self, *a, **k):
            return None

    from app.modules.ingestion import mapping
    monkeypatch.setattr(mapping, "build_release", lambda *a, **k: calls.append(k))
    await ing._auto_release(FakeConn(), "j")
    assert not calls


async def test_auto_release_skips_when_folder_refused_it(monkeypatch):
    """Папка сняла авто-выпуск, оставив автоподготовку.

    Это разные решения: «готовь без меня» не означает «выпускай без меня».
    Проверяем именно пару (подготовка включена, выпуск снят) — иначе тест
    прошёл бы и в том случае, если бы код по-прежнему смотрел на один тумблер.
    """
    calls = []

    class FakeConn:
        async def fetchrow(self, sql, *args):
            if "extraction_jobs ej" in sql:
                return {"id": "j", "template_match": "exact", "document_version_id": "v",
                        "reporting_period_start": "2026-08-12", "original_filename": "f.xlsx",
                        "auto_prepare": True, "auto_release": False,
                        "folder_name": "Папка", "organization_id": "o"}
            return None
        async def fetch(self, *a, **k):
            return []
        async def fetchval(self, *a, **k):
            return None

    from app.modules.ingestion import mapping
    monkeypatch.setattr(mapping, "build_release", lambda *a, **k: calls.append(k))
    await ing._auto_release(FakeConn(), "j")
    assert not calls


async def test_auto_release_never_breaks_extraction(monkeypatch):
    """Осечка выпуска не должна ронять распознавание: файл уже разобран."""
    class BoomConn:
        async def fetchrow(self, *a, **k):
            raise RuntimeError("база недоступна")
        async def fetch(self, *a, **k):
            raise RuntimeError("база недоступна")
        async def fetchval(self, *a, **k):
            raise RuntimeError("база недоступна")

    # Не должно бросить наружу — иначе результат разбора потеряется.
    await ing._auto_release(BoomConn(), "j")
