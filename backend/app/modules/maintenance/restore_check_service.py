"""Проверка резервной копии восстановлением: итог последней проверки и «Проверить сейчас».

Саму проверку делает ХОСТ (`restore-check.sh`: временная база рядом с рабочей,
восстановление набора, сверка) — у контейнера API нет docker.sock. Раз в
месяц ночью её запускает `restore-check-watch.sh` из хостового наблюдателя,
а по кнопке — заявка-файл на общем томе (тот же приём, что у «Запустить бэкап
сейчас»). Здесь — чтение итога и решение, о чём сказать человеку.

🔴 Отсутствие проверки — не «всё хорошо». Если наблюдатель не установлен или
перестал запускаться, итог просто стареет; поэтому кроме «провалилась» есть
«давно не проверялась» и «ни разу не проверялась», и на экране они видны.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from .backup_service import TRIGGER_DIR

RESULT_FILE = TRIGGER_DIR / "restore-check.result"
REQUEST_FILE = TRIGGER_DIR / "restore-check.request"
LOCK_DIR = TRIGGER_DIR / "restore-check.lock"
NOTIFIED_FILE = TRIGGER_DIR / "restore-check.notified"

# Плановая проверка — раз в 30 дней (RESTORE_CHECK_DAYS у хостового скрипта).
# «Просрочена» — с запасом в неделю: ночное окно могло прийтись на обновление
# или на день без свежего бэкапа, и это ещё не повод тревожить.
PLANNED_DAYS = 30
OVERDUE_DAYS = PLANNED_DAYS + 7


def _read_result() -> Optional[dict]:
    try:
        return json.loads(RESULT_FILE.read_text())
    except (OSError, ValueError):
        return None


def status(now: Optional[datetime] = None) -> dict:
    """Итог последней проверки и что из него следует.

    `state`: ok / diff (набор цел, рабочая база ушла вперёд — это норма) /
    fail / never (ни разу) / overdue (последняя проверка старше `OVERDUE_DAYS`).
    """
    now = now or datetime.now(timezone.utc)
    last = _read_result()
    age_days = None
    if last and last.get("ts"):
        try:
            ts = datetime.fromisoformat(str(last["ts"]).replace("Z", "+00:00"))
            age_days = (now - ts).days
        except ValueError:
            age_days = None
    if last is None:
        state = "never"
    elif last.get("status") == "fail" or last.get("ok") is False:
        state = "fail"
    elif age_days is not None and age_days > OVERDUE_DAYS:
        state = "overdue"
    else:
        state = last.get("status") or "ok"
    return {
        "state": state,
        "last": last,
        "age_days": age_days,
        "planned_days": PLANNED_DAYS,
        "running": LOCK_DIR.exists(),
        "pending": REQUEST_FILE.exists(),
    }


def request_now(login: str) -> None:
    TRIGGER_DIR.mkdir(parents=True, exist_ok=True)
    REQUEST_FILE.write_text(json.dumps({
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "requested_by": login,
    }, ensure_ascii=False))


def to_announce(now: Optional[datetime] = None) -> Optional[dict]:
    """О чём сообщить управляющим — один раз на каждое новое состояние.

    Провал объявляется по отметке времени итога (новая проверка — новое
    сообщение), просрочка — один раз, пока не появится свежая проверка.
    «Ни разу» не объявляется: на только что установленной системе бэкапа ещё
    может не быть, а первая проверка придёт сама через месяц.
    """
    st = status(now)
    if st["state"] not in ("fail", "overdue"):
        return None
    key = f"{st['state']}:{(st['last'] or {}).get('ts')}"
    try:
        if NOTIFIED_FILE.read_text().strip() == key:
            return None
    except OSError:
        pass
    return {"key": key, **st}


def mark_announced(key: str) -> None:
    TRIGGER_DIR.mkdir(parents=True, exist_ok=True)
    NOTIFIED_FILE.write_text(key)
