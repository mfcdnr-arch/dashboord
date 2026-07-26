#!/usr/bin/env bash
# Резервное копирование прод-стека: дамп PostgreSQL (pg_dump -Fc) + том MinIO (tar).
# Ротация: хранит последние BACKUP_KEEP наборов (по умолчанию 7).
#   ./backup.sh                       # → backups/YYYYmmdd-HHMMSS/{db.dump,minio.tgz}
#   BACKUP_DIR=/mnt/backup BACKUP_KEEP=14 ./backup.sh
set -euo pipefail
cd "$(dirname "$0")"

# `|| true`: без .env.prod grep выходит с кодом 2 → set -e/pipefail убил бы скрипт.
env_get() { { grep -E "^$1=" .env.prod 2>/dev/null | cut -d= -f2- | tail -1; } || true; }
PGUSER="$(env_get POSTGRES_USER)"; PGUSER="${PGUSER:-dashbord}"
PGDB="$(env_get POSTGRES_DB)"; PGDB="${PGDB:-dashbord}"
BACKUP_DIR="${BACKUP_DIR:-backups}"
BACKUP_KEEP="${BACKUP_KEEP:-7}"
MINIO_VOLUME="${MINIO_VOLUME:-dashbord-prod_miniodata}"

TS="$(date +%Y%m%d-%H%M%S)"
DEST="$BACKUP_DIR/$TS"
mkdir -p "$DEST"
log() { printf '\033[1;34m[backup]\033[0m %s\n' "$1"; }

docker inspect dashbord_prod_postgres >/dev/null 2>&1 || { echo "postgres контейнер не запущен — нечего бэкапить"; exit 1; }

log "Дамп PostgreSQL → $DEST/db.dump"
docker exec dashbord_prod_postgres pg_dump -U "$PGUSER" -d "$PGDB" -Fc > "$DEST/db.dump"

# Проверка ВОССТАНОВИМОСТИ: pg_restore читает оглавление дампа. Битый/пустой
# дамп ловим сразу в момент бэкапа, а не в день аварии.
log "Проверка восстановимости дампа (pg_restore --list)…"
docker exec -i dashbord_prod_postgres pg_restore --list < "$DEST/db.dump" >/dev/null \
  || { echo "[backup] ОШИБКА: дамп не читается pg_restore — бэкап НЕ валиден"; exit 1; }

log "Архив тома MinIO ($MINIO_VOLUME) → $DEST/minio.tgz"
if docker volume inspect "$MINIO_VOLUME" >/dev/null 2>&1; then
  docker run --rm -v "$MINIO_VOLUME":/data:ro -v "$PWD/$DEST":/backup alpine \
    tar czf /backup/minio.tgz -C /data . 2>/dev/null || log "предупреждение: том MinIO пуст или недоступен"
  # Целостность архива MinIO (tar читается до конца).
  if [ -f "$DEST/minio.tgz" ]; then
    tar -tzf "$DEST/minio.tgz" >/dev/null \
      || { echo "[backup] ОШИБКА: архив MinIO повреждён — бэкап НЕ валиден"; exit 1; }
  fi
else
  log "том $MINIO_VOLUME не найден — пропуск MinIO"
fi

# метаданные набора
{ echo "created_at=$TS"; echo "pg_db=$PGDB"; docker exec dashbord_prod_postgres psql -U "$PGUSER" -d "$PGDB" -tAc "select count(*)||' миграций' from schema_migrations" 2>/dev/null; } > "$DEST/meta.txt"

log "Размер набора: $(du -sh "$DEST" | cut -f1)"

# Ротация: оставить последние BACKUP_KEEP
log "Ротация (храним $BACKUP_KEEP)…"
ls -1dt "$BACKUP_DIR"/*/ 2>/dev/null | tail -n +$((BACKUP_KEEP + 1)) | while read -r old; do
  log "удаляю старый: $old"; rm -rf "$old"
done

log "Готово: $DEST"
