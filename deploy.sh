#!/usr/bin/env bash
# Dashboard — развёртывание прод-стека на реальном сервере (Astra/ВМ/LAN/офлайн).
# Идемпотентно: повторный запуск накатывает только новые миграции и обновляет образы.
#
#   cp .env.prod.example .env.prod   # и заполнить секреты
#   ./deploy.sh
#
# Флаги: --no-build (не пересобирать образы), --skip-smoke (без проверки),
#        --skip-backup (не бэкапить БД перед накатом миграций при обновлении).
set -euo pipefail
cd "$(dirname "$0")"

NO_BUILD=""; SKIP_SMOKE=""; TLS=""; SKIP_BACKUP=""
for a in "$@"; do
  case "$a" in
    --no-build) NO_BUILD=1 ;;
    --skip-smoke) SKIP_SMOKE=1 ;;
    --tls) TLS=1 ;;
    --skip-backup) SKIP_BACKUP=1 ;;
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
env_get_port() { grep -E "^$1=" .env.prod 2>/dev/null | cut -d= -f2 || true; }

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

# Порты — после того, как .env.prod точно существует (свежесгенерирован выше
# или уже был). Нужны и для предполётной проверки занятости (ниже), и для
# smoke/итогового URL.
WEB_PORT="$(env_get_port WEB_PORT)"; WEB_PORT="${WEB_PORT:-8090}"
HTTPS_PORT="$(env_get_port HTTPS_PORT)"; HTTPS_PORT="${HTTPS_PORT:-8443}"

# Урок ВМ из проекта DS: сбитые часы → apt/подписи/сборка ломаются. Пробуем
# исправить сами (self-heal при установке), не просто предупреждаем.
if command -v timedatectl >/dev/null 2>&1; then
  if ! timedatectl show -p NTPSynchronized --value 2>/dev/null | grep -q yes; then
    log "Время системы не синхронизировано (NTP) — пробую включить синхронизацию…"
    if timedatectl set-ntp true 2>/dev/null; then
      sleep 2
      if timedatectl show -p NTPSynchronized --value 2>/dev/null | grep -q yes; then
        log "NTP включён и синхронизирован."
      else
        log "ВНИМАНИЕ: включил NTP, но синхронизация ещё не подтверждена (нужно время). При офлайн-сборке образов возможны сбои проверки подписей."
      fi
    else
      log "ВНИМАНИЕ: не удалось включить NTP автоматически (нет прав/systemd-timesyncd?). При офлайн-сборке образов возможны сбои проверки подписей."
    fi
  fi
fi

# Малый объём ОЗУ — предупреждение (advisory, не блокирует), как и NTP выше:
# Postgres+Redis+MinIO+API+worker+nginx на слабой машине рискуют упасть в OOM.
if [ -f /proc/meminfo ]; then
  MEM_KB="$(awk '/^MemTotal:/{print $2}' /proc/meminfo)"
  MEM_GB=$(( ${MEM_KB:-0} / 1024 / 1024 ))
  if [ "$MEM_GB" -lt 4 ]; then
    log "ВНИМАНИЕ: обнаружено ~${MEM_GB} ГБ ОЗУ. Рекомендуется от 4 ГБ (Postgres+Redis+MinIO+API+worker+nginx) — возможны сбои под нагрузкой."
  fi
fi

# Предполётная проверка занятости портов: явная понятная ошибка ДО docker
# compose up, а не запутанное "bind: address already in use" из глубины Docker.
# Свой же контейнер от прошлого деплоя (dashbord_prod_*) на этом порту — не
# конфликт, compose его пересоздаст; посторонний Docker-контейнер или процесс
# хоста на этом порту — конфликт, останавливаем деплой с понятной подсказкой.
check_port_free() {
  local port="$1" label="$2"
  local holder
  holder="$(docker ps --format '{{.Names}}\t{{.Ports}}' 2>/dev/null | awk -F'\t' -v p=":${port}->" '$2 ~ p {print $1}' | head -1)"
  if [ -n "$holder" ]; then
    case "$holder" in
      dashbord_prod_*) return 0 ;;
      *) err "Порт $port ($label) уже занят Docker-контейнером «$holder» (не нашим). Остановите его или измените ${label}_PORT в .env.prod."; exit 1 ;;
    esac
  fi
  if command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    err "Порт $port ($label) уже занят процессом на хосте (не Docker). Освободите его или измените ${label}_PORT в .env.prod."
    exit 1
  fi
}
log "Проверка занятости портов ($WEB_PORT${TLS:+, $HTTPS_PORT})…"
check_port_free "$WEB_PORT" WEB
[ -n "$TLS" ] && check_port_free "$HTTPS_PORT" HTTPS

# 2. Сборка образов -------------------------------------------------------
if [ -z "$NO_BUILD" ]; then
  log "Сборка образов (api, web)…"
  $COMPOSE build
else
  log "Пропуск сборки (--no-build)"
fi

# 3. Бэкап перед миграциями (только при ОБНОВЛЕНИИ — БД от прошлого деплоя уже
#    работает; на первой установке бэкапировать нечего, backup.sh сам увидит
#    отсутствие контейнера). Форвард-миграции необратимы — это страховка перед
#    накатом новых, а не автоматический откат (см. фазу 3: down-миграции для
#    29 уже накопленных миграций признаны более рискованными, чем полезными).
if [ -n "$SKIP_BACKUP" ]; then
  log "Бэкап перед миграциями пропущен (--skip-backup)."
elif docker inspect -f '{{.State.Running}}' dashbord_prod_postgres >/dev/null 2>&1; then
  log "Обнаружена работающая БД от предыдущего деплоя — бэкап перед накатом миграций…"
  if ./backup.sh; then
    log "Бэкап перед миграциями создан."
  else
    err "Бэкап перед миграциями не удался — прерываю деплой, миграции НЕ применены."
    err "Проверьте место на диске/backups/, либо повторите с --skip-backup осознанно."
    exit 1
  fi
else
  log "Свежая установка (БД ещё не поднята) — бэкап перед миграциями не требуется."
fi

# 4. Запуск всего стека ---------------------------------------------------
# Порядок гарантирует compose через depends_on:
#   postgres(healthy) → migrate(completed_successfully) → api/worker(healthy) → web.
# Если миграции упадут — migrate завершится с ненулевым кодом, api не стартует,
# и `up` вернёт ошибку (обрабатываем ниже).
log "Запуск стека (миграции применятся автоматически перед API)…"
if ! $COMPOSE up -d; then
  err "запуск не удался. Логи миграций:"; $COMPOSE logs --tail 40 migrate || true
  exit 1
fi

# 5. Ожидание готовности --------------------------------------------------
wait_api_healthy() {
  local tries="$1"
  for i in $(seq 1 "$tries"); do
    if docker inspect -f '{{.State.Health.Status}}' dashbord_prod_api 2>/dev/null | grep -q healthy; then
      return 0
    fi
    sleep 3
  done
  return 1
}
log "Ожидание готовности API…"
if ! wait_api_healthy 30; then
  # Автопочинка при установке: контейнер иногда не поднимается с первого раза
  # (гонка при инициализации, временная недоступность зависимости) — один
  # автоматический перезапуск и повторное ожидание, прежде чем сдаться.
  log "API не стал healthy за ~90с — пробую самопочинку (перезапуск api/worker)…"
  $COMPOSE restart api worker || true
  if ! wait_api_healthy 20; then
    err "API так и не стал healthy после перезапуска — смотрите: $COMPOSE logs api"
    exit 1
  fi
  log "Самопочинка помогла — API поднялся после перезапуска."
fi

# 6. Smoke-проверка -------------------------------------------------------
# (WEB_PORT/HTTPS_PORT уже прочитаны в начале скрипта — используются и для
# предполётной проверки портов, и здесь.)

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
