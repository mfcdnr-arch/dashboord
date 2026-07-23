#!/usr/bin/env bash
# Восстановление из набора backup.sh. ПЕРЕЗАПИСЫВАЕТ данные — требует подтверждения.
#   ./restore.sh backups/YYYYmmdd-HHMMSS
# По умолчанию восстанавливает и БД, и MinIO. Флаги: --db-only, --minio-only, --yes.
set -euo pipefail
cd "$(dirname "$0")"

SET=""; DB=1; MINIO=1; YES=""
for a in "$@"; do
  case "$a" in
    --db-only) MINIO=0 ;;
    --minio-only) DB=0 ;;
    --yes) YES=1 ;;
    -*) echo "Неизвестный флаг: $a"; exit 2 ;;
    *) SET="$a" ;;
  esac
done
[ -n "$SET" ] && [ -d "$SET" ] || { echo "Укажите каталог набора: ./restore.sh backups/<TS>"; exit 2; }

env_get() { grep -E "^$1=" .env.prod 2>/dev/null | cut -d= -f2- | tail -1; }
PGUSER="$(env_get POSTGRES_USER)"; PGUSER="${PGUSER:-dashbord}"
PGDB="$(env_get POSTGRES_DB)"; PGDB="${PGDB:-dashbord}"
MINIO_VOLUME="${MINIO_VOLUME:-dashbord-prod_miniodata}"
log() { printf '\033[1;34m[restore]\033[0m %s\n' "$1"; }

if [ -z "$YES" ]; then
  printf '\033[1;33mВНИМАНИЕ:\033[0m перезапишет данные из %s (db=%s, minio=%s). Продолжить? [y/N] ' "$SET" "$DB" "$MINIO"
  read -r ans; [ "$ans" = y ] || [ "$ans" = Y ] || { echo "отменено"; exit 1; }
fi

if [ "$DB" = 1 ]; then
  [ -f "$SET/db.dump" ] || { echo "нет $SET/db.dump"; exit 1; }
  docker inspect dashbord_prod_postgres >/dev/null 2>&1 || { echo "postgres не запущен"; exit 1; }
  log "Восстановление БД из $SET/db.dump (--clean --if-exists)…"
  docker exec -i dashbord_prod_postgres pg_restore -U "$PGUSER" -d "$PGDB" --clean --if-exists < "$SET/db.dump"
  log "БД восстановлена."
fi

if [ "$MINIO" = 1 ] && [ -f "$SET/minio.tgz" ]; then
  log "Восстановление тома MinIO ($MINIO_VOLUME)…"
  # Останавливаем minio, очищаем том, распаковываем архив.
  docker compose -f docker-compose.prod.yml stop minio >/dev/null 2>&1 || true
  docker run --rm -v "$MINIO_VOLUME":/data -v "$PWD/$SET":/backup:ro alpine \
    sh -c "rm -rf /data/* /data/..?* /data/.[!.]* 2>/dev/null; tar xzf /backup/minio.tgz -C /data"
  docker compose -f docker-compose.prod.yml start minio >/dev/null 2>&1 || true
  log "MinIO восстановлен."
fi

log "Готово. Проверьте: ./smoke.sh"
