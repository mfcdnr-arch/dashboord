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

# Результат ЛЮБОГО запуска — планового тоже (20.09.2026).
# Раньше его писал только ops-trigger-watch.sh, то есть след оставался лишь
# от кнопки «Запустить сейчас»: ночной бэкап, падавший месяцами, на экране
# никак не проявлялся.
TRIGGER_DIR="${OPS_TRIGGER_DIR:-ops-triggers}"
RESULT_FILE="$TRIGGER_DIR/backup.result"
RESULT_WRITTEN=""

write_result() {  # $1 — true/false, $2 — сообщение
  [ -n "$RESULT_WRITTEN" ] && return 0
  RESULT_WRITTEN=1
  mkdir -p "$TRIGGER_DIR" 2>/dev/null || return 0
  printf '{"ts":"%s","ok":%s,"message":"%s","set":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" "$TS" > "$RESULT_FILE" 2>/dev/null || true
}

# Ловим ЛЮБОЙ выход, включая падение по set -e: незаписанный результат
# означал бы «бэкап как будто и не запускался».
on_exit() {
  code=$?
  if [ "$code" != 0 ]; then
    # Набор остаётся на диске для диагностики, но помечен: без этого файла
    # каталог со свежей отметкой времени выглядел бы годным бэкапом.
    echo "Бэкап не завершён, код $code. Набор НЕ пригоден для восстановления." \
      > "$DEST/FAILED.txt" 2>/dev/null || true
    write_result false "Бэкап завершился с ошибкой (код $code) — набор $TS непригоден"
  fi
}
trap on_exit EXIT

docker inspect dashbord_prod_postgres >/dev/null 2>&1 || { echo "postgres контейнер не запущен — нечего бэкапить"; exit 1; }

# Пишем во ВРЕМЕННЫЙ файл и переименовываем только после проверки: при обрыве
# pg_dump редирект уже создал бы `db.dump` (пустой или обрезанный), и набор
# выглядел бы готовым. Файла `db.dump` не существует, пока он не проверен.
log "Дамп PostgreSQL → $DEST/db.dump"
docker exec dashbord_prod_postgres pg_dump -U "$PGUSER" -d "$PGDB" -Fc > "$DEST/db.dump.part"

# Проверка ВОССТАНОВИМОСТИ: pg_restore читает оглавление дампа. Битый/пустой
# дамп ловим сразу в момент бэкапа, а не в день аварии.
log "Проверка восстановимости дампа (pg_restore --list)…"
docker exec -i dashbord_prod_postgres pg_restore --list < "$DEST/db.dump.part" >/dev/null \
  || { echo "[backup] ОШИБКА: дамп не читается pg_restore — бэкап НЕ валиден"; exit 1; }
mv "$DEST/db.dump.part" "$DEST/db.dump"

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

# Ротация выполняется ТОЛЬКО после успешного набора, и это намеренно: удалять
# старые годные копии в тот момент, когда свежая не удалась, — прямой путь
# остаться вовсе без бэкапа. При провале скрипт до сюда не доходит.
# Провалившиеся наборы (с FAILED.txt) в счёт хранения не берём — иначе
# несколько неудач подряд вытеснили бы последнюю годную копию.
log "Ротация (храним $BACKUP_KEEP)…"
# Годные наборы — по BACKUP_KEEP.
for old in $(ls -1dt "$BACKUP_DIR"/*/ 2>/dev/null | while read -r d; do
      [ -f "$d/FAILED.txt" ] || echo "$d"; done | tail -n +$((BACKUP_KEEP + 1))); do
  log "удаляю старый: $old"; rm -rf "$old" || log "не удалось удалить $old (чужой владелец?) — пропуск"
done
# Провалившиеся — своим счётом: несколько подряд не должны вытеснить годные,
# но и копиться без предела им незачем, последних трёх для разбора хватит.
for old in $(ls -1dt "$BACKUP_DIR"/*/ 2>/dev/null | while read -r d; do
      [ -f "$d/FAILED.txt" ] && echo "$d"; done | tail -n +4); do
  log "удаляю неудачный: $old"; rm -rf "$old" || true
done

write_result true "Бэкап выполнен успешно"
log "Готово: $DEST"
