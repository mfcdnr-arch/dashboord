"""Статус бэкапа + «Запустить сейчас» — графическое управление вместо голого
CLI (backup.sh/backup-schedule.sh).

Резервное копирование (pg_dump + том MinIO) физически выполняется НА ХОСТЕ
(backup.sh дёргает `docker exec` — из контейнера API так нельзя, доступа к
docker.sock у него нет и не будет по соображениям безопасности). Поэтому:

- «Статус» — только чтение общего тома `backups/` (что реально лежит на
  диске — единственный источник правды, не воображаемое расписание).
- «Запустить сейчас» — API кладёт файл-триггер на общий том; хостовой
  наблюдатель `ops-trigger-watch.sh` (регистрируется backup-schedule.sh)
  видит его, гонит backup.sh и пишет результат обратно. Без docker.sock
  в контейнере и без прав root у API — только договорённость через файл.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

BACKUPS_DIR = Path(os.environ.get("BACKUPS_DIR", "/app/backups"))
TRIGGER_DIR = Path(os.environ.get("OPS_TRIGGER_DIR", "/app/ops-triggers"))
TRIGGER_FILE = TRIGGER_DIR / "backup.request"
RESULT_FILE = TRIGGER_DIR / "backup.result"


def _dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def get_status() -> dict:
    sets = []
    if BACKUPS_DIR.exists():
        for d in sorted((p for p in BACKUPS_DIR.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)[:10]:
            db_dump = d / "db.dump"
            minio_tgz = d / "minio.tgz"
            sets.append({
                "name": d.name,
                "created_at": datetime.fromtimestamp(d.stat().st_mtime, tz=timezone.utc).isoformat(),
                "db_dump_bytes": db_dump.stat().st_size if db_dump.exists() else None,
                "minio_tgz_bytes": minio_tgz.stat().st_size if minio_tgz.exists() else None,
            })
    last_result = None
    if RESULT_FILE.exists():
        try:
            last_result = json.loads(RESULT_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            last_result = None
    return {
        "sets": sets,
        "pending": TRIGGER_FILE.exists(),
        "last_manual_result": last_result,
        "watcher_configured": TRIGGER_DIR.exists(),
    }


def is_pending() -> bool:
    return TRIGGER_FILE.exists()


def request_now(login: str) -> None:
    TRIGGER_DIR.mkdir(parents=True, exist_ok=True)
    TRIGGER_FILE.write_text(json.dumps({
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "requested_by": login,
    }, ensure_ascii=False))
