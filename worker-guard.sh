#!/usr/bin/env bash
# Сторож фонового воркера: поднимает его, если он перестал отмечаться.
#
# Зачем это на ХОСТЕ, а не в приложении. Воркер (arq) выполняет весь конвейер,
# которого не видно на экране: распознавание файлов, авто-выпуск данных,
# уведомления, свежесть, ретенцию, автоархив. Его остановка не даёт ни одного
# видимого признака — дашборды показывают прежние цифры. Попросить о
# собственном перезапуске он не может, а сторож самодиагностики живёт ВНУТРИ
# него и умирает вместе с ним. У контейнера API доступа к docker.sock нет и не
# будет (осознанное решение проекта), поэтому поднять воркер способен только
# хост. Docker сам этого не делает: он помечает контейнер unhealthy, но по
# unhealthy не перезапускает.
#
# Запускается хостовым наблюдателем ops-trigger-watch.sh — раз в минуту
# (systemd-таймер, ставится вместе с backup-schedule.sh install).
#
# Живость определяется по СОБСТВЕННОМУ health-ключу arq в Redis: воркер пишет
# его сам раз в health_check_interval с TTL = интервал + 1 с, то есть
# «протухание» обеспечивает Redis, а не наш код (см. backend/app/modules/
# system/worker_health.py — API читает тот же ключ).
set -euo pipefail
cd "$(dirname "$0")"
REPO="$(pwd)"

# `|| true`: без .env.prod grep выходит с кодом 2 → set -e/pipefail убил бы скрипт.
env_get() { { grep -E "^$1=" .env.prod 2>/dev/null | cut -d= -f2- | tail -1; } || true; }
# Значение из окружения сильнее .env.prod — так сторожа можно прогнать на
# дев-стенде или отладить на сервере, не трогая файл с боевыми секретами.
PGUSER="${PGUSER:-$(env_get POSTGRES_USER)}"; PGUSER="${PGUSER:-dashbord}"
PGDB="${PGDB:-$(env_get POSTGRES_DB)}"; PGDB="${PGDB:-dashbord}"

WORKER_CONTAINER="${WORKER_CONTAINER:-dashbord_prod_worker}"
REDIS_CONTAINER="${REDIS_CONTAINER:-dashbord_prod_redis}"
PG_CONTAINER="${PG_CONTAINER:-dashbord_prod_postgres}"
TRIGGER_DIR="${OPS_TRIGGER_DIR:-$REPO/ops-triggers}"

# Ключ arq: default_queue_name + health_check_key_suffix. Что API и воркер
# по-прежнему сходятся на нём, держит тест test_worker_health.py.
HEALTH_KEY="${GUARD_HEALTH_KEY:-arq:queue:health-check}"

# Потолок попыток. Без него циклически падающий воркер перезапускался бы вечно,
# и автоматика прятала бы причину падения — ровно то, чего мы избегаем.
# Значение живёт в «Настройках» (system_settings), а не в коде: сколько попыток
# допустимо — решение эксплуатации. Зашитое число расходилось бы с тем, что
# показывает экран, и администратор менял бы настройку впустую.
# Порядок: переменная окружения (отладка) → настройки → умолчание 3.
MAX_RESTARTS_DEFAULT=3
WINDOW_SEC="${GUARD_WINDOW_SEC:-3600}"
# Ждём подтверждения: успех объявляем, только увидев ключ снова, а не по факту
# того, что `docker restart` не дал ошибку.
WAIT_SEC="${GUARD_WAIT_SEC:-90}"
POLL_SEC="${GUARD_POLL_SEC:-5}"

ALIVE_FILE="$TRIGGER_DIR/worker-guard.alive"
OFF_FILE="$TRIGGER_DIR/worker-autorestart.off"
LOG_FILE="$TRIGGER_DIR/worker-restarts.log"
RESULT="$TRIGGER_DIR/worker.result"
LOCK="$TRIGGER_DIR/worker-guard.lock.d"  # каталог, см. ниже

mkdir -p "$TRIGGER_DIR"

now() { date +%s; }

# Склонение: «1 попытка / 3 попытки / 5 попыток». Ловушка 11–14 («11 попыток»,
# а не «11 попытка») — та же, что у помощника plural на фронте.
plural() {  # $1 число, $2 одна, $3 две, $4 пять
  local n=$1 n10=$(( $1 % 10 )) n100=$(( $1 % 100 ))
  if [ "$n100" -ge 11 ] && [ "$n100" -le 14 ]; then echo "$4"
  elif [ "$n10" = 1 ]; then echo "$2"
  elif [ "$n10" -ge 2 ] && [ "$n10" -le 4 ]; then echo "$3"
  else echo "$4"; fi
}
iso() { date -u +%Y-%m-%dT%H:%M:%SZ; }  # переносимо (GNU/BSD), не -Is (только GNU)

# Результат читает API (GET /maintenance/backup/status → блок воркера) и
# показывает в «Здоровье системы». Это единственный канал, работающий, когда
# воркер так и не поднялся: уведомление в таком случае слать некому.
write_result() {  # $1 state, $2 message, $3 ok(true/false)
  printf '{"ts":"%s","state":"%s","ok":%s,"message":"%s"}\n' "$(iso)" "$1" "$3" "$2" > "$RESULT"
}

health_key_present() {
  [ "$(docker exec "$REDIS_CONTAINER" redis-cli exists "$HEALTH_KEY" 2>/dev/null | tr -d '\r\n ')" = "1" ]
}

# 🔴 Самоотметка — ПЕРВЫМ делом, до замка, паузы и любых проверок. Сторож
# должен отмечаться при КАЖДОМ запуске, в том числе когда вмешиваться не во
# что: иначе остановку его собственного таймера нельзя отличить от «всё
# хорошо», и автоматика перестала бы работать молча — ровно тот дефект, против
# которого она заведена. Читает отметку API («Здоровье системы»).
date +%s > "$ALIVE_FILE" 2>/dev/null || true

# Потолок из настроек. Недоступна БД — работаем по умолчанию: сторож не должен
# вставать из-за того, что не смог прочитать настройку.
if [ -z "${GUARD_MAX_RESTARTS:-}" ]; then
  MAX_RESTARTS="$(docker exec -i "$PG_CONTAINER" psql -U "$PGUSER" -d "$PGDB" -tAc \
    "select worker_restart_max_per_hour from system_settings where id=1" 2>/dev/null | tr -d '\r\n ' || true)"
  case "$MAX_RESTARTS" in (''|*[!0-9]*) MAX_RESTARTS="$MAX_RESTARTS_DEFAULT" ;; esac
else
  MAX_RESTARTS="$GUARD_MAX_RESTARTS"
fi

# Один экземпляр за раз: наблюдатель запускается раз в минуту, а ожидание
# подтверждения длится дольше — без блокировки два сторожа перезапускали бы
# воркер наперегонки и вдвое быстрее выбирали потолок попыток.
#
# 🔴 Замок каталогом, а не flock. `mkdir` атомарен на любой POSIX-системе, а
# flock есть не везде (на macOS его нет вовсе, в минимальных образах — не
# всегда). Первая версия писала `flock -n 9 || exit 0`, и на машине без flock
# сторож МОЛЧА не делал ничего: команда не найдена → ненулевой код → выход.
# Тихий отказ защиты от тихих отказов — худшее, что тут можно построить.
if ! mkdir "$LOCK" 2>/dev/null; then
  # Замок старше 10 минут остался от экземпляра, который умер, не убрав за
  # собой (kill, перезагрузка). Иначе сторож молчал бы до конца времён.
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +10 2>/dev/null)" ]; then
    rmdir "$LOCK" 2>/dev/null || true
    mkdir "$LOCK" 2>/dev/null || exit 0
  else
    exit 0
  fi
fi
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

# (1) Плановое обслуживание: воркер остановлен человеком намеренно.
if [ -f "$OFF_FILE" ]; then
  exit 0
fi

# (2) Стек погашен целиком — это решение человека, а не сбой.
[ "$(docker inspect -f '{{.State.Running}}' "$REDIS_CONTAINER" 2>/dev/null)" = "true" ] || exit 0

# (3) 🔴 Различаем «воркер молчит» и «Redis недоступен». Если лежит сам Redis,
# живость воркера проверить нечем: перезапуск не поможет (воркер может быть
# цел), а состояние, в котором он упал, затрёт и уведёт разбор не туда.
if ! docker exec "$REDIS_CONTAINER" redis-cli ping 2>/dev/null | grep -qi pong; then
  write_result "unknown" "Redis недоступен — живость воркера не проверить, перезапуск не выполнялся" false
  exit 0
fi

# (4) Ключ на месте — вмешиваться не во что.
if health_key_present; then
  exit 0
fi

# (5) Потолок попыток за окно.
CUTOFF=$(( $(now) - WINDOW_SEC ))
RECENT=0
if [ -f "$LOG_FILE" ]; then
  # В журнале только метки времени, по одной в строке; старые отсекаем окном.
  RECENT=$(awk -v c="$CUTOFF" '$1 > c' "$LOG_FILE" | wc -l | tr -d ' ')
fi
if [ "$RECENT" -ge "$MAX_RESTARTS" ]; then
  write_result "suspended" \
    "Автоперезапуск приостановлен: $RECENT $(plural "$RECENT" попытка попытки попыток) за последний час не помогли. Воркер падает повторно — нужен разбор причины, см. логи контейнера $WORKER_CONTAINER" \
    false
  exit 0
fi

# (6) Перезапуск. Метку пишем ДО попытки: сорвись скрипт на середине, попытка
# всё равно должна быть сосчитана — иначе потолок обходится падениями.
echo "$(now)" >> "$LOG_FILE"
# Журнал не растёт вечно: держим только сутки.
if [ -f "$LOG_FILE" ]; then
  DAY_AGO=$(( $(now) - 86400 ))
  awk -v c="$DAY_AGO" '$1 > c' "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
fi
ATTEMPT=$(( RECENT + 1 ))

RESTART_OK=true
docker restart "$WORKER_CONTAINER" >/dev/null 2>&1 || RESTART_OK=false

# (7) Подтверждение: ждём, пока воркер снова отметится в Redis.
HEALTHY=false
if [ "$RESTART_OK" = true ]; then
  WAITED=0
  while [ "$WAITED" -lt "$WAIT_SEC" ]; do
    sleep "$POLL_SEC"
    WAITED=$(( WAITED + POLL_SEC ))
    if health_key_present; then HEALTHY=true; break; fi
  done
fi

if [ "$HEALTHY" = true ]; then
  STATUS_AFTER="worker_ok"
  MSG="Воркер не отмечался и был перезапущен автоматически (попытка $ATTEMPT из $MAX_RESTARTS) — конвейер снова работает"
else
  STATUS_AFTER="worker_down"
  MSG="Перезапуск воркера выполнен (попытка $ATTEMPT из $MAX_RESTARTS), но он так и не отметился — нужен разбор причины"
fi
write_result "$STATUS_AFTER" "$MSG" "$HEALTHY"

# (8) 🔴 Перезапуск не должен быть молчаливым. Запись в system_heal_log — то же
# место, куда пишутся все автопочинки; экран «История починок» отрисует её сам,
# а сторож воркера после оживления разошлёт уведомление управляющим.
# Долларовое кавычение ($j$) — чтобы кавычки внутри JSON не ломали SQL.
ACTIONS=$(printf '[{"name":"Фоновый воркер: перезапуск","ok":%s,"result":"%s","attempt":%s}]' \
  "$HEALTHY" "$MSG" "$ATTEMPT")
docker exec -i "$PG_CONTAINER" psql -U "$PGUSER" -d "$PGDB" -v ON_ERROR_STOP=1 -q -c \
  "insert into system_heal_log(triggered_by, status_before, status_after, healthy, actions) \
   values('auto', 'worker_down', '$STATUS_AFTER', $HEALTHY, \$j\$$ACTIONS\$j\$::jsonb)" \
  >/dev/null 2>&1 || true
