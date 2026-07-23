#!/usr/bin/env bash
# Dashboard — развёртывание прод-стека на реальном сервере (Astra/ВМ/LAN/офлайн).
# Идемпотентно: повторный запуск накатывает только новые миграции и обновляет образы.
#
#   cp .env.prod.example .env.prod   # и заполнить секреты
#   ./deploy.sh
#
# Флаги: --no-build (не пересобирать образы), --skip-smoke (без проверки).
set -euo pipefail
cd "$(dirname "$0")"

COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.prod"
NO_BUILD=""; SKIP_SMOKE=""
for a in "$@"; do
  case "$a" in
    --no-build) NO_BUILD=1 ;;
    --skip-smoke) SKIP_SMOKE=1 ;;
    *) echo "Неизвестный флаг: $a"; exit 2 ;;
  esac
done

log() { printf '\033[1;34m[deploy]\033[0m %s\n' "$1"; }
err() { printf '\033[1;31m[deploy] ОШИБКА:\033[0m %s\n' "$1" >&2; }

# 1. Предусловия ----------------------------------------------------------
log "Проверка предусловий…"
command -v docker >/dev/null || { err "docker не установлен"; exit 1; }
docker compose version >/dev/null 2>&1 || { err "нужен docker compose v2"; exit 1; }
docker info >/dev/null 2>&1 || { err "демон docker недоступен (запущен? права?)"; exit 1; }

[ -f .env.prod ] || { err "нет .env.prod — скопируйте из .env.prod.example и заполните секреты"; exit 1; }

# Плейсхолдеры-секреты не должны утечь в прод.
if grep -q "CHANGE_ME" .env.prod; then
  err "в .env.prod остались значения CHANGE_ME — задайте реальные секреты"; exit 1
fi

# Урок ВМ из проекта DS: сбитые часы → apt/подписи/сборка ломаются. Предупредим.
if command -v timedatectl >/dev/null 2>&1; then
  if ! timedatectl show -p NTPSynchronized --value 2>/dev/null | grep -q yes; then
    log "ВНИМАНИЕ: время системы не синхронизировано (NTP). При офлайн-сборке образов возможны сбои проверки подписей."
  fi
fi

# 2. Сборка образов -------------------------------------------------------
if [ -z "$NO_BUILD" ]; then
  log "Сборка образов (api, web)…"
  $COMPOSE build
else
  log "Пропуск сборки (--no-build)"
fi

# 3. Запуск всего стека ---------------------------------------------------
# Порядок гарантирует compose через depends_on:
#   postgres(healthy) → migrate(completed_successfully) → api/worker(healthy) → web.
# Если миграции упадут — migrate завершится с ненулевым кодом, api не стартует,
# и `up` вернёт ошибку (обрабатываем ниже).
log "Запуск стека (миграции применятся автоматически перед API)…"
if ! $COMPOSE up -d; then
  err "запуск не удался. Логи миграций:"; $COMPOSE logs --tail 40 migrate || true
  exit 1
fi

# 4. Ожидание готовности --------------------------------------------------
log "Ожидание готовности API…"
for i in $(seq 1 30); do
  if docker inspect -f '{{.State.Health.Status}}' dashbord_prod_api 2>/dev/null | grep -q healthy; then
    break
  fi
  sleep 3
  [ "$i" = 30 ] && { err "API не стал healthy за ~90с — смотрите: $COMPOSE logs api"; exit 1; }
done

# 5. Smoke-проверка -------------------------------------------------------
if [ -z "$SKIP_SMOKE" ]; then
  WEB_PORT="$(grep -E '^WEB_PORT=' .env.prod | cut -d= -f2 || true)"; WEB_PORT="${WEB_PORT:-8090}"
  ./smoke.sh "$WEB_PORT" || { err "smoke-проверка не пройдена"; exit 1; }
fi

WEB_PORT="$(grep -E '^WEB_PORT=' .env.prod | cut -d= -f2 || true)"; WEB_PORT="${WEB_PORT:-8090}"
log "Готово. Веб-интерфейс: http://<адрес-сервера>:${WEB_PORT}/"
