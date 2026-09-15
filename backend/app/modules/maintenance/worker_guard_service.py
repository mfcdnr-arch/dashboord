"""Сторож фонового воркера со стороны приложения: состояние и управление.

Сам перезапуск выполняет ХОСТ (`worker-guard.sh`): у контейнера API нет и не
будет доступа к docker.sock. Здесь — то, что должно быть доступно человеку с
экрана: видеть, работает ли сторож вообще, приостанавливать его на время
обслуживания и сбрасывать счётчик попыток, когда причина устранена.

🔴 Самонаблюдение. Сторож обязан отмечать КАЖДЫЙ свой запуск, даже когда всё
в порядке: остановись его systemd-таймер — автоматика перестала бы работать
молча, то есть повторила бы ровно тот дефект, против которого заведена.
Отсутствие отметки и «всё хорошо» — разные вещи, и на экране они выглядят
по-разному.

Договорённость через файлы на общем томе — единственный канал между
контейнером и хостом (тот же приём, что у «Запустить бэкап сейчас»).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from .backup_service import TRIGGER_DIR

ALIVE_FILE = TRIGGER_DIR / "worker-guard.alive"
RESULT_FILE = TRIGGER_DIR / "worker.result"
OFF_FILE = TRIGGER_DIR / "worker-autorestart.off"
ATTEMPTS_FILE = TRIGGER_DIR / "worker-restarts.log"

# Сторож запускается раз в минуту. Час молчания — уже отказ, а не задержка;
# запас намеренно щедрый, чтобы перезагрузка сервера не давала ложной тревоги.
WATCHER_STALE_SEC = 3600
ATTEMPT_WINDOW_SEC = 3600

# Подсказки ДОПОЛНЯЮТ заголовок на экране, а не повторяют его: «Сторож ни разу
# не отмечался. Сторож ни разу не отмечался — …» читается как сбой вёрстки.
INSTALL_HINT = ("Возможно, его таймер не зарегистрирован на сервере — "
                "выполните `./backup-schedule.sh install`. Пока его нет, упавший воркер "
                "никто не поднимет")


def _read_int(path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def attempts_last_hour() -> int:
    """Сколько перезапусков сторож сделал за последний час."""
    if not ATTEMPTS_FILE.exists():
        return 0
    cutoff = time.time() - ATTEMPT_WINDOW_SEC
    n = 0
    try:
        for line in ATTEMPTS_FILE.read_text().splitlines():
            try:
                if float(line.strip()) > cutoff:
                    n += 1
            except ValueError:
                continue
    except OSError:
        return 0
    return n


def last_result() -> dict | None:
    """Итог последнего срабатывания сторожа, если он был.

    None — сторож ни разу не вмешивался; выдумывать «всё хорошо» нельзя, это
    разные вещи. Битый файл (обрыв записи) тоже даёт None: экран важнее.
    """
    if not RESULT_FILE.exists():
        return None
    try:
        data = json.loads(RESULT_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def status() -> dict:
    """Полное состояние сторожа для экрана «Здоровье системы»."""
    seen = _read_int(ALIVE_FILE)
    if seen is None:
        watcher, seen_at, hint = "never", None, INSTALL_HINT
    elif time.time() - seen > WATCHER_STALE_SEC:
        watcher, seen_at, hint = "stale", _iso(seen), (
            "Проверьте таймер dashbord-backup-watch на сервере: пока сторож молчит, "
            "упавший воркер никто не поднимет")
    else:
        watcher, seen_at, hint = "ok", _iso(seen), None

    paused_by = None
    if OFF_FILE.exists():
        try:
            paused_by = json.loads(OFF_FILE.read_text()).get("by")
        except (json.JSONDecodeError, OSError):
            paused_by = "неизвестно кем"

    return {
        "watcher": watcher,
        "watcher_seen_at": seen_at,
        "watcher_hint": hint,
        "paused": OFF_FILE.exists(),
        "paused_by": paused_by,
        "attempts_last_hour": attempts_last_hour(),
        "last_result": last_result(),
    }


def set_paused(paused: bool, login: str) -> None:
    """Приостановить автоперезапуск (плановое обслуживание) или вернуть его.

    Кто и когда приостановил — пишем в сам файл: иначе через неделю никто не
    вспомнит, почему воркер не поднимается, и это выглядело бы поломкой.
    """
    TRIGGER_DIR.mkdir(parents=True, exist_ok=True)
    if paused:
        OFF_FILE.write_text(json.dumps(
            {"by": login, "at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False))
    elif OFF_FILE.exists():
        OFF_FILE.unlink()


def reset_attempts(login: str) -> int:
    """Сбросить счётчик попыток: причину починили, ждать час незачем.

    Возвращает, сколько попыток было списано, — чтобы на экране было видно, что
    действие что-то изменило, а не «нажал и ничего».
    """
    had = attempts_last_hour()
    if ATTEMPTS_FILE.exists():
        try:
            ATTEMPTS_FILE.unlink()
        except OSError:
            return 0
    # Прежний итог больше не отражает положения дел: попытки обнулены, и
    # висящее «приостановлено» вводило бы в заблуждение до первого срабатывания.
    if RESULT_FILE.exists():
        try:
            RESULT_FILE.unlink()
        except OSError:
            pass
    return had
