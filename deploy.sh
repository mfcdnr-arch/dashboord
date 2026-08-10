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

log() { printf '\033[1;34m[deploy]\033[0m %s\n' "$1"; }
err() { printf '\033[1;31m[deploy] ОШИБКА:\033[0m %s\n' "$1" >&2; }
env_get_port() { grep -E "^$1=" .env.prod 2>/dev/null | cut -d= -f2 || true; }

# HTTP-клиент для ожидания веб-прокси и smoke: curl, а если его нет (базовая
# Astra Linux) — python3. См. http-lib.sh.
. ./http-lib.sh

# 1. Предусловия ----------------------------------------------------------
log "Проверка предусловий…"
command -v docker >/dev/null || { err "docker не установлен"; exit 1; }
http_client_available || { err "нужен curl или python3 — нечем проверить готовность стека."; exit 1; }
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

# HTTPS в LAN: генерируем самоподписанный сертификат и включаем TLS-оверлей.
# CN/SAN — сначала из окружения (TLS_CN=... TLS_SAN=... ./deploy.sh --tls),
# иначе — из .env.prod (удобно один раз задать имя/IP сервера и не вводить
# каждый раз), иначе — localhost.
COMPOSE_FILES="-f docker-compose.prod.yml"
if [ -n "$TLS" ]; then
  TLS_CN="${TLS_CN:-$(env_get_port TLS_CN)}"
  TLS_SAN="${TLS_SAN:-$(env_get_port TLS_SAN)}"
  [ -f certs/tls.crt ] || ./gen-tls.sh "${TLS_CN:-localhost}" "${TLS_SAN:-}"
  COMPOSE_FILES="$COMPOSE_FILES -f docker-compose.tls.yml"
fi
COMPOSE="docker compose $COMPOSE_FILES --env-file .env.prod"

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

# Каталоги-источники bind-монтирования (docker-compose.prod.yml: ./backups:ro,
# ./ops-triggers). Оба в .gitignore, значит в поставку из `git archive` не
# попадают (пустые каталоги git не хранит) — и Docker создаёт их сам, от ROOT,
# потому что демон работает под root. После этого backup.sh, ночной таймер и
# кнопка «Запустить сейчас» из UI (все работают от обычного пользователя)
# получают «Отказано в доступе», а повторный deploy.sh падает на бэкапе перед
# миграциями. Создаём заранее от себя; если каталог уже успел появиться от
# root — чиним владельца (самолечение, а не отказ с невнятной ошибкой).
ensure_dir_writable() {
  local d="$1"
  [ -d "$d" ] || mkdir -p "$d"
  if [ -w "$d" ]; then return 0; fi
  log "Каталог $d недоступен на запись (создан Docker от root?) — исправляю владельца…"
  if [ "$(id -u)" = 0 ]; then
    chown -R "$(id -u):$(id -g)" "$d" 2>/dev/null || true
  elif sudo -n true 2>/dev/null; then
    sudo chown -R "$(id -u):$(id -g)" "$d" 2>/dev/null || true
  fi
  if [ -w "$d" ]; then return 0; fi
  err "Каталог $d недоступен на запись (чужой владелец или права)."
  err "Выполните: sudo chown -R \$(id -u):\$(id -g) $(pwd)/$d — и повторите запуск."
  exit 1
}
log "Проверка рабочих каталогов (backups, ops-triggers)…"
ensure_dir_writable backups
ensure_dir_writable ops-triggers

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

# Первая это установка или обновление — определяем ДО запуска стека, по наличию
# тома с данными БД. Нужно для итоговой памятки: на первой установке пароли из
# .env.prod ещё «боевые» (учётки заводятся из них), при обновлении они могли быть
# давно сменены в самой системе, и печатать их как актуальные — врать.
FRESH_INSTALL=""
docker volume inspect dashbord-prod_pgdata >/dev/null 2>&1 || FRESH_INSTALL=1

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

# Перечитать адрес API веб-прокси.
# nginx резолвит имя `api` ОДИН РАЗ при старте и держит IP в памяти. При
# обновлении, где менялся только бэкенд, compose пересоздаёт контейнер api
# (новый IP), а web оставляет как есть — образ-то не менялся. В итоге nginx
# стучится по старому адресу и отдаёт 502 на все запросы к API, хотя сам API
# healthy. Ровно это случилось на боевом сервере 10.08.2026.
# Перезапуск nginx стоит секунду и снимает проблему целиком.
log "Перезапуск веб-прокси (обновить адрес API)…"
$COMPOSE restart web >/dev/null 2>&1 || true

# Дождаться, пока nginx начнёт принимать соединения: web стартует последним,
# и на быстрой машине smoke иначе прилетает раньше bind'а порта (гонка).
if [ -n "$TLS" ]; then WAIT_URL="https://localhost:${HTTPS_PORT}/"; else WAIT_URL="http://localhost:${WEB_PORT}/"; fi
log "Ожидание готовности веб-прокси…"
for i in $(seq 1 30); do
  code="$(http_code "$WAIT_URL" 3)"
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

# 7. Итоговая памятка: адрес и учётки ------------------------------------
# Пароли печатает и gen-secrets.sh, но ТОЛЬКО когда сам их сгенерировал. Если
# админ принёс готовый .env.prod (перенос с другого стенда, свои пароли), он не
# увидел бы ни адреса входа, ни логинов — поэтому печатаем здесь всегда.
ADMIN_LOGIN_V="$(env_get_port ADMIN_LOGIN)"; ADMIN_LOGIN_V="${ADMIN_LOGIN_V:-admin}"
SUPERADMIN_LOGIN_V="$(env_get_port SUPERADMIN_LOGIN)"; SUPERADMIN_LOGIN_V="${SUPERADMIN_LOGIN_V:-superadmin}"
ADMIN_PW_V="$(env_get_port ADMIN_PASSWORD)"
SUPERADMIN_PW_V="$(env_get_port SUPERADMIN_PASSWORD)"

if [ -n "$TLS" ]; then
  URL="https://<адрес-сервера>:${HTTPS_PORT}/"
  log "Готово. Веб-интерфейс: $URL (самоподписанный сертификат — примите в браузере)"
else
  URL="http://<адрес-сервера>:${WEB_PORT}/"
  log "Готово. Веб-интерфейс: $URL"
fi

echo
echo "  ┌─ ВХОД В СИСТЕМУ ─────────────────────────────────────────────────────────────"
printf "  │  адрес       : %s\n" "$URL"
printf "  │  %-11s : %s\n" "$SUPERADMIN_LOGIN_V" "${SUPERADMIN_PW_V:-<нет в .env.prod>}"
printf "  │  %-11s : %s\n" "$ADMIN_LOGIN_V" "${ADMIN_PW_V:-<нет в .env.prod>}"
if [ -n "$FRESH_INSTALL" ]; then
  echo "  │"
  echo "  │  Пароли ВРЕМЕННЫЕ — система потребует сменить их при первом входе."
else
  echo "  │"
  echo "  │  ВНИМАНИЕ: это значения из .env.prod. Обновление их НЕ применяет —"
  echo "  │  если пароль уже меняли в системе, действует тот, что задан в системе."
fi
echo "  └──────────────────────────────────────────────────────────────────────────────"
echo
