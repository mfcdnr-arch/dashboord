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

NO_BUILD=""; SKIP_SMOKE=""; TLS=""
for a in "$@"; do
  case "$a" in
    --no-build) NO_BUILD=1 ;;
    --skip-smoke) SKIP_SMOKE=1 ;;
    --tls) TLS=1 ;;
    *) echo "Неизвестный флаг: $a"; exit 2 ;;
  esac
done

# HTTPS в LAN: генерируем самоподписанный сертификат и включаем TLS-оверлей.
COMPOSE_FILES="-f docker-compose.prod.yml"
if [ -n "$TLS" ]; then
  [ -f certs/tls.crt ] || ./gen-tls.sh "${TLS_CN:-localhost}" "${TLS_SAN:-}"
  COMPOSE_FILES="$COMPOSE_FILES -f docker-compose.tls.yml"
fi
COMPOSE="docker compose $COMPOSE_FILES --env-file .env.prod"

log() { printf '\033[1;34m[deploy]\033[0m %s\n' "$1"; }
err() { printf '\033[1;31m[deploy] ОШИБКА:\033[0m %s\n' "$1" >&2; }

# 1. Предусловия ----------------------------------------------------------
log "Проверка предусловий…"
command -v docker >/dev/null || { err "docker не установлен"; exit 1; }
docker compose version >/dev/null 2>&1 || { err "нужен docker compose v2 (плагин docker-compose-plugin)"; exit 1; }
# service_completed_successfully и ожидание условий depends_on требуют Compose v2+.
CV="$(docker compose version --short 2>/dev/null | sed 's/^v//')"
CV_MAJOR="${CV%%.*}"
if ! { [ -n "$CV_MAJOR" ] && [ "$CV_MAJOR" -ge 2 ] 2>/dev/null; }; then
  err "нужен Docker Compose v2+ (найдено: ${CV:-нет}). На Astra: установить docker-compose-plugin v2."
  exit 1
fi
docker info >/dev/null 2>&1 || { err "демон docker недоступен (запущен? права?)"; exit 1; }

# Нет .env.prod — сгенерировать сильные секреты автоматически (без ручного ввода).
if [ ! -f .env.prod ]; then
  log "Файл .env.prod не найден — генерирую сильные секреты (gen-secrets.sh)…"
  ./gen-secrets.sh
fi

# Плейсхолдеры-секреты не должны утечь в прод.
if grep -q "CHANGE_ME" .env.prod; then
  err "в .env.prod остались значения CHANGE_ME — задайте реальные секреты (или удалите .env.prod и запустите снова для авто-генерации)"; exit 1
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
WEB_PORT="$(grep -E '^WEB_PORT=' .env.prod | cut -d= -f2 || true)"; WEB_PORT="${WEB_PORT:-8090}"
HTTPS_PORT="$(grep -E '^HTTPS_PORT=' .env.prod | cut -d= -f2 || true)"; HTTPS_PORT="${HTTPS_PORT:-8443}"

# Дождаться, пока nginx начнёт принимать соединения: web стартует последним,
# и на быстрой машине smoke иначе прилетает раньше bind'а порта (гонка).
if [ -n "$TLS" ]; then WAIT_URL="https://localhost:${HTTPS_PORT}/"; else WAIT_URL="http://localhost:${WEB_PORT}/"; fi
log "Ожидание готовности веб-прокси…"
for i in $(seq 1 30); do
  code="$(curl -ks -o /dev/null -w '%{http_code}' -m 3 "$WAIT_URL" || true)"
  [ "$code" != "000" ] && break
  sleep 1
  [ "$i" = 30 ] && { err "веб-прокси не отвечает на $WAIT_URL за ~30с — смотрите: $COMPOSE logs web"; exit 1; }
done

if [ -z "$SKIP_SMOKE" ]; then
  if [ -n "$TLS" ]; then
    ./smoke.sh "$HTTPS_PORT" https || { err "smoke-проверка (HTTPS) не пройдена"; exit 1; }
  else
    ./smoke.sh "$WEB_PORT" || { err "smoke-проверка не пройдена"; exit 1; }
  fi
fi

if [ -n "$TLS" ]; then
  log "Готово. Веб-интерфейс: https://<адрес-сервера>:${HTTPS_PORT}/ (самоподписанный сертификат — примите в браузере)"
else
  log "Готово. Веб-интерфейс: http://<адрес-сервера>:${WEB_PORT}/"
fi
