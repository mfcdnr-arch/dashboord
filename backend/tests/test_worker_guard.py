"""Автоперезапуск фонового воркера — поведение хостового сторожа.

Почему тест гоняет САМ bash-скрипт, а не его описание. Перезапуск живёт на
хосте: у контейнера API нет и не будет доступа к docker.sock, поэтому поднять
упавший воркер может только `worker-guard.sh`, который дёргает хостовой
наблюдатель раз в минуту. Проверять тут нечего, кроме настоящего поведения
скрипта, — а его ошибки дорогие: молчаливый отказ оставит конвейер стоять,
лишний перезапуск затрёт причину падения.

Вместо docker в PATH подставляется заглушка, которая пишет все вызовы в файл и
отвечает по сценарию, заданному переменными окружения. Так проверяется главное:
ЧТО скрипт решил сделать, а не то, что он при этом напечатал.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Скрипты поставки монтируются в /deploy (в контейнере смонтирован только
# backend/); при локальном прогоне берём их из корня репозитория.
_DEPLOY = Path("/deploy")
ROOT = _DEPLOY if (_DEPLOY / "worker-guard.sh").exists() else Path(__file__).resolve().parents[2]
GUARD = ROOT / "worker-guard.sh"

# Пропуска по отсутствию файла НЕТ намеренно: скрипт — часть поставки, и его
# исчезновение это регрессия, а не повод молча сделать набор зелёным.

STUB = """#!/usr/bin/env bash
# Заглушка docker: пишет вызов в $CALLS и отвечает по сценарию.
echo "$*" >> "$CALLS"
case "$*" in
  *"inspect -f {{.State.Running}}"*) echo "${STUB_RUNNING:-true}" ;;
  *"redis-cli ping"*)   [ "${STUB_REDIS:-up}" = up ] && echo PONG || exit 1 ;;
  *"redis-cli exists"*) echo "${STUB_KEY:-0}" ;;
  # 🔴 Запрос потолка разбирается ДО «restart»: в имени колонки
  # worker_restart_max_per_hour есть подстрока «restart», и обратный порядок
  # отдавал бы SQL-запрос ветке перезапуска (наступили при написании теста).
  *worker_restart_max_per_hour*) echo "${STUB_MAX:-}" ;;
  *"restart"*)          [ "${STUB_RESTART:-ok}" = ok ] || exit 1 ;;
  *psql*)               exit 0 ;;
esac
exit 0
"""


def run_guard(tmp_path: Path, **env) -> tuple[subprocess.CompletedProcess, list[str], Path]:
    """Прогнать сторож с подставным docker. Возвращает (результат, вызовы docker, каталог триггеров)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    calls = tmp_path / "calls.txt"
    # Очищаем, а не создаём: каталог переиспользуется между прогонами в одном
    # тесте (потолок попыток), и накопленные вызовы прошлой итерации выглядели
    # бы как лишние перезапуски.
    calls.write_text("")
    (bin_dir / "docker").write_text(STUB)
    (bin_dir / "docker").chmod(0o755)
    trig = tmp_path / "ops-triggers"
    trig.mkdir(exist_ok=True)

    e = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "CALLS": str(calls),
        "OPS_TRIGGER_DIR": str(trig),
        # Ожидание подтверждения — короткое: тест не должен стоять полторы минуты.
        "GUARD_WAIT_SEC": "1",
        "GUARD_POLL_SEC": "1",
        **{k: str(v) for k, v in env.items()},
    }
    p = subprocess.run(["bash", str(GUARD)], capture_output=True, text=True, env=e, timeout=60)
    return p, calls.read_text().splitlines(), trig


def restarts(calls: list[str]) -> list[str]:
    return [c for c in calls if c.startswith("restart ")]


def test_zhivoy_vorker_ne_trogaem(tmp_path):
    """Ключ на месте — вмешиваться не во что. Лишний перезапуск рвёт задания."""
    p, calls, trig = run_guard(tmp_path, STUB_KEY="1")
    assert p.returncode == 0, p.stderr
    assert restarts(calls) == [], "живой воркер перезапускать нельзя"


def test_molchaschiy_vorker_perezapuskaetsya(tmp_path):
    """Redis отвечает, ключа нет — воркер молчит дольше отведённого, поднимаем."""
    p, calls, trig = run_guard(tmp_path, STUB_KEY="0")
    assert p.returncode == 0, p.stderr
    assert len(restarts(calls)) == 1, f"ожидался ровно один перезапуск, вызовы: {calls}"


def test_upavshiy_redis_ne_daet_povoda_trogat_vorker(tmp_path):
    """🔴 Главный тест. Если лежит САМ Redis, живость воркера проверить нечем.

    Перезапуск тут бессмыслен (воркер может быть цел) и вреден: он затрёт
    состояние, в котором упал, и уведёт разбор не туда.
    """
    p, calls, trig = run_guard(tmp_path, STUB_REDIS="down")
    assert p.returncode == 0, p.stderr
    assert restarts(calls) == [], "при недоступном Redis воркер трогать нельзя"


def test_pogashenniy_stek_ne_podnimaem(tmp_path):
    """Стек остановлен целиком — это решение человека, а не сбой."""
    p, calls, trig = run_guard(tmp_path, STUB_RUNNING="false")
    assert restarts(calls) == [], "погашенный стек сторож поднимать не должен"


def test_potolok_popytok_ostanavlivaet_karusel(tmp_path):
    """Циклически падающий воркер не должен перезапускаться вечно.

    Иначе автоматика прячет причину падения — ровно то, чего опасался заказчик.
    После потолка попытки прекращаются, а причина названа в файле-результате,
    который читает экран «Здоровье системы».
    """
    seen = []
    for i in range(4):
        p, calls, trig = run_guard(tmp_path, STUB_KEY="0")
        seen.append(len(restarts(calls)))
    assert seen[:3] == [1, 1, 1], f"первые три попытки должны пройти: {seen}"
    assert seen[3] == 0, "четвёртая попытка в пределах часа не должна выполняться"
    result = (trig / "worker.result").read_text()
    assert "приостанов" in result.lower(), f"причина остановки не названа: {result}"
    # Склонение: «3 попытки», а не «3 попыток». Сообщение читает человек, и
    # неграмотность в нём подрывает доверие к самому сообщению.
    assert "3 попытки" in result, f"число попыток не просклонено: {result}"


def test_stop_fayl_otklyuchaet_avtomatiku(tmp_path):
    """Плановое обслуживание: воркер остановлен человеком намеренно."""
    trig = tmp_path / "ops-triggers"
    trig.mkdir(exist_ok=True)
    (trig / "worker-autorestart.off").write_text("обслуживание")
    p, calls, _ = run_guard(tmp_path, STUB_KEY="0")
    assert restarts(calls) == [], "при стоп-файле автоматика вмешиваться не должна"


def test_perezapusk_popadaet_v_zhurnal_pochinok(tmp_path):
    """Перезапуск не должен быть молчаливым: запись в system_heal_log.

    Без неё «само починилось» скроет от заказчика, что воркер падает ежедневно.
    """
    p, calls, trig = run_guard(tmp_path, STUB_KEY="0")
    psql = [c for c in calls if "psql" in c]
    assert psql, f"перезапуск не записан в system_heal_log: {calls}"
    assert any("system_heal_log" in c for c in psql), psql


def test_nablyudatel_zovet_storozha_bez_zayavki_na_bekap(tmp_path):
    """🔴 Сторож обязан вызываться при КАЖДОМ запуске наблюдателя.

    ops-trigger-watch.sh выходит сразу, если заявки на бэкап нет, — а это
    подавляющее большинство запусков (раз в минуту). Встань вызов сторожа
    после этой строки, он не выполнился бы никогда, и вся схема автоперезапуска
    молча не работала бы.
    """
    watch = ROOT / "ops-trigger-watch.sh"
    assert watch.exists(), "ops-trigger-watch.sh не смонтирован"
    text = watch.read_text()
    guard_pos = text.index("worker-guard.sh")
    exit_pos = text.index('[ -f "$REQUEST" ] || exit 0')
    assert guard_pos < exit_pos, "вызов сторожа стоит ПОСЛЕ выхода по отсутствию заявки — он не выполнится"


def test_dva_ekzemplyara_ne_perezapuskayut_naperegonki(tmp_path):
    """🔴 Замок обязан работать там, где нет flock.

    Первая версия писала `flock -n 9 || exit 0`, и на машине без flock сторож
    молча не делал НИЧЕГО — тихий отказ защиты от тихих отказов. Поймано живой
    проверкой, а не тестом: на macOS flock отсутствует. Теперь замок — каталог
    (`mkdir` атомарен везде), и этот тест держит его смысл: пока один сторож
    ждёт подтверждения, второй не должен перезапускать воркер повторно.
    """
    import threading

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    calls = tmp_path / "calls.txt"
    calls.write_text("")
    (bin_dir / "docker").write_text(STUB)
    (bin_dir / "docker").chmod(0o755)
    trig = tmp_path / "ops-triggers"
    trig.mkdir(exist_ok=True)
    env = {
        **os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "CALLS": str(calls),
        "OPS_TRIGGER_DIR": str(trig), "STUB_KEY": "0",
        # Первый сторож задержится в ожидании подтверждения — за это время
        # стартует второй и должен упереться в замок.
        "GUARD_WAIT_SEC": "6", "GUARD_POLL_SEC": "1",
    }
    results = []

    def run():
        results.append(subprocess.run(["bash", str(GUARD)], capture_output=True, text=True, env=env, timeout=60))

    first = threading.Thread(target=run)
    first.start()
    import time
    time.sleep(1.5)  # первый уже в ожидании
    run()            # второй — в том же потоке
    first.join()

    got = restarts(calls.read_text().splitlines())
    assert len(got) == 1, f"второй сторож перезапустил воркер повторно: {got}"


def test_storozh_otmechaet_kazhdyy_svoy_zapusk(tmp_path):
    """🔴 Самонаблюдение: сторож обязан отмечаться, даже когда всё в порядке.

    Остановись его systemd-таймер — автоматика перестала бы работать МОЛЧА,
    то есть повторила бы ровно тот дефект, против которого заведена. Отметка
    при каждом запуске (а не только при перезапуске) — единственный способ
    отличить «сторож работает, вмешиваться не во что» от «сторожа нет».
    """
    p, calls, trig = run_guard(tmp_path, STUB_KEY="1")  # воркер жив, делать нечего
    alive = trig / "worker-guard.alive"
    assert alive.exists(), "сторож не отметился при здоровом воркере"
    assert int(alive.read_text().strip()) > 0


def test_otmetka_stavitsya_dazhe_na_pauze(tmp_path):
    """На паузе сторож всё равно запускается — и это надо отличать от «его нет»."""
    trig = tmp_path / "ops-triggers"
    trig.mkdir(exist_ok=True)
    (trig / "worker-autorestart.off").write_text('{"by":"admin"}')
    p, calls, _ = run_guard(tmp_path, STUB_KEY="0")
    assert (trig / "worker-guard.alive").exists(), "на паузе сторож не отметился"
    assert restarts(calls) == [], "на паузе перезапускать нельзя"


def test_potolok_beretsya_iz_nastroek_a_ne_iz_koda(tmp_path):
    """Потолок правится мышью в «Настройках»: скрипт читает его из БД.

    Зашитое число расходилось бы с тем, что показывает экран, и администратор
    менял бы настройку впустую.
    """
    # В настройках 5 — значит пятая попытка ещё проходит, шестая нет.
    seen = []
    for _ in range(6):
        p, calls, trig = run_guard(tmp_path, STUB_KEY="0", STUB_MAX="5")
        seen.append(len(restarts(calls)))
    assert seen[:5] == [1] * 5, f"потолок из настроек не применился: {seen}"
    assert seen[5] == 0, "шестая попытка сверх настроенного потолка"


def test_bez_dostupa_k_nastroykam_rabotaet_umolchanie(tmp_path):
    """БД недоступна — сторож не должен вставать: перезапускает по умолчанию 3 раза."""
    seen = []
    for _ in range(4):
        p, calls, trig = run_guard(tmp_path, STUB_KEY="0", STUB_MAX="")
        seen.append(len(restarts(calls)))
    assert seen == [1, 1, 1, 0], f"умолчание не сработало: {seen}"
