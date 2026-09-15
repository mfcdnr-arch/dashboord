"""Живость фонового воркера видна снаружи: /health и «Здоровье системы».

Зачем это вообще. Воркер выполняет весь конвейер, которого не видно на экране:
распознавание файлов, авто-выпуск данных, уведомления, свежесть, ретенцию,
автоархив и сторожевую самодиагностику. Его остановка не даёт ни одного
видимого признака — дашборды показывают прежние цифры, загрузка проходит, — а
сторож молчит по устройству: он живёт ВНУТРИ воркера и умирает вместе с ним.
Значит обнаружить смерть может только сторона API, и до 15.09 она этого не
делала: в списке служб были PostgreSQL, Redis и MinIO, воркера не было.

Здесь проверяется именно наблюдаемость, а не сам arq: ключ подкладывается и
убирается руками, как это делает живой воркер.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import cache
from app.modules.system import worker_health

# Строка ровно того формата, что пишет arq (Worker.record_health).
ARQ_LINE = "Sep-15 12:34:56 j_complete=7 j_failed=2 j_retried=0 j_ongoing=1 queued=3"


async def _set_key(value: str | None):
    """Подкладываем/убираем health-ключ так же, как это делает воркер."""
    await cache.connect()
    assert cache._redis is not None, "тест требует живого Redis"
    if value is None:
        await cache._redis.delete(worker_health.HEALTH_KEY)
    else:
        await cache._redis.set(worker_health.HEALTH_KEY, value)


async def test_key_matches_the_one_worker_writes():
    """Ключ, который читает API, обязан совпадать с тем, что пишет воркер.

    Это главный тест файла: если WorkerSettings когда-нибудь получит своё
    `queue_name` или `health_check_key`, API начнёт читать несуществующий ключ
    и будет ВЕЧНО показывать «воркер упал» при живом воркере — отказ хуже
    исходного дефекта, потому что ему перестанут верить.
    """
    from app.modules.ingestion.worker import WorkerSettings
    assert getattr(WorkerSettings, "health_check_key", None) is None, (
        "WorkerSettings задал свой health_check_key — обновите HEALTH_KEY в worker_health")
    assert getattr(WorkerSettings, "queue_name", None) in (None, "arq:queue"), (
        "WorkerSettings сменил очередь — HEALTH_KEY в worker_health больше не совпадает")
    assert worker_health.HEALTH_KEY == "arq:queue:health-check"
    # Интервал должен оставаться коротким: TTL ключа = интервал + 1 с, то есть
    # он и определяет, как быстро видна смерть. Умолчание arq — ЧАС.
    assert WorkerSettings.health_check_interval <= 120, (
        "при большом интервале смерть воркера видна лишь через час")


async def test_live_worker_is_reported_with_its_numbers():
    await _set_key(ARQ_LINE)
    try:
        st = await worker_health.read()
        assert st["state"] == "ok" and st["ok"] is True
        # Числа разбираются из строки arq: живой воркер с очередью — тоже сигнал.
        assert st["queued"] == 3 and st["failed"] == 2 and st["ongoing"] == 1
    finally:
        await _set_key(None)


async def test_silent_worker_is_reported_as_down_everywhere(client, admin_headers):
    """Ключа нет → и публичный /health, и экран говорят о простое.

    Именно этот случай раньше не был виден нигде.
    """
    await _set_key(None)

    r = await client.get("/health")
    assert r.status_code == 200, "health обязан отвечать 200 — по нему живость САМОГО API"
    body = r.json()
    assert body["worker"] == "down"
    # Упавший воркер НЕ делает API «degraded»: по этому полю healthcheck решает,
    # не перезапустить ли API, а перезапускать исправный API бессмысленно.
    assert body["status"] == "ok"

    sys = (await client.get("/reports/system", headers=admin_headers)).json()
    w = [s for s in sys["services"] if s["name"] == "Фоновый воркер"]
    assert w, "воркера нет в списке служб — его смерть снова невидима"
    assert w[0]["ok"] is False and w[0]["state"] == "down"
    assert "остановлены" in (w[0]["detail"] or ""), "отказ должен называть последствие, а не только факт"
    # Общий статус системы обязан просесть: конвейер стоит.
    assert sys["status"] == "degraded"


async def test_live_worker_makes_health_green(client, admin_headers):
    await _set_key(ARQ_LINE)
    try:
        assert (await client.get("/health")).json()["worker"] == "ok"
        sys = (await client.get("/reports/system", headers=admin_headers)).json()
        w = [s for s in sys["services"] if s["name"] == "Фоновый воркер"][0]
        assert w["ok"] is True and w["queued"] == 3
    finally:
        await _set_key(None)


def test_parse_ignores_foreign_format():
    """Формат строки — не наш, он может измениться: разбор не должен падать."""
    assert worker_health.parse_info("") == {}
    assert worker_health.parse_info("что-то совсем другое") == {}
    assert worker_health.parse_info(ARQ_LINE)["j_complete"] == 7
