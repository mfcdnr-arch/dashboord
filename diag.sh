#!/usr/bin/env bash
# Самодиагностика прод-стека → архив для офлайн-поддержки (по образцу collect_diag из DS).
# Собирает: версии, статус/health сервисов, последние логи, применённые миграции,
# диск/ресурсы. Секреты НЕ включаются.
#   ./diag.sh            # → diag-YYYYmmdd-HHMMSS.tgz
set -eu
cd "$(dirname "$0")"

COMPOSE="docker compose -f docker-compose.prod.yml"
env_get() { grep -E "^$1=" .env.prod 2>/dev/null | cut -d= -f2- | tail -1; }
WEB_PORT="$(env_get WEB_PORT)"; WEB_PORT="${WEB_PORT:-8090}"
PGUSER="$(env_get POSTGRES_USER)"; PGUSER="${PGUSER:-dashbord}"
PGDB="$(env_get POSTGRES_DB)"; PGDB="${PGDB:-dashbord}"

TS="$(date +%Y%m%d-%H%M%S)"
DIR="diag-$TS"
mkdir -p "$DIR"

save() { # save <файл> <команда...>
  f="$DIR/$1"; shift
  { echo "# \$ $*"; "$@" 2>&1; } > "$f" || true
}

echo "[diag] сбор в $DIR …"
save versions.txt sh -c "docker version; echo; docker compose version"
save compose-ps.txt sh -c "$COMPOSE ps -a"
save docker-df.txt docker system df
save disk.txt df -h
save mem.txt sh -c "uptime; echo; (free -h 2>/dev/null || vm_stat 2>/dev/null || true)"

# Логи каждого сервиса (последние 500 строк)
for s in postgres redis minio migrate api worker web; do
  save "log-$s.txt" sh -c "$COMPOSE logs --tail 500 $s"
done

# Health API-контейнера
save inspect-api.txt sh -c "docker inspect -f '{{json .State.Health}}' dashbord_prod_api 2>/dev/null | (command -v python3 >/dev/null && python3 -m json.tool || cat)"

# /health через nginx
save health.json sh -c "curl -sf -m 5 http://localhost:$WEB_PORT/health || echo 'health недоступен'"

# Применённые миграции
save migrations.txt docker exec dashbord_prod_postgres psql -U "$PGUSER" -d "$PGDB" -c "select filename, applied_at from schema_migrations order by filename"

tar czf "$DIR.tgz" "$DIR" && rm -rf "$DIR"
echo "[diag] Готово: $DIR.tgz — приложите к обращению в поддержку."
