#!/usr/bin/env bash
# Регулярная проверка резервной копии НАСТОЯЩИМ восстановлением (restore-check.sh).
#
# Зачем. backup.sh проверяет, что дамп читается; restore-check.sh — что из него
# действительно поднимается база. До 11.10.2026 вторая проверка запускалась
# руками, и на боевом прошла ровно один раз (24.09). Бэкап, который годами
# «успешен», но ни разу не восстанавливался, — это надежда, а не страховка.
#
# Что делает. Зовётся из ops-trigger-watch.sh (хостовой таймер гонит его раз в
# минуту — отдельный таймер не заводим, как и для сторожей воркера и
# доступности: на развёрнутых серверах он заработает с обычной поставкой).
# Запускает restore-check.sh В ФОНЕ, если:
#   • лежит заявка ops-triggers/restore-check.request («Проверить сейчас» в
#     «Здоровье системы»), или
#   • с последней проверки прошло RESTORE_CHECK_DAYS (30) дней, сейчас ночное
#     окно RESTORE_CHECK_HOUR (04, после ночного бэкапа в 02:00) и есть
#     годный набор новее последней проверки — проверять тот же набор второй
#     раз незачем.
# Итог пишет сам restore-check.sh (ops-triggers/restore-check.result) — его
# читает API и показывает в «Здоровье системы»; провал приходит уведомлением.
#
# В фоне — потому что проверка идёт минуты (боевой: 52 с на 1,1 ГБ), а
# наблюдатель обязан отработать за секунды: он же отвечает за бэкап по кнопке.
# Пауза обслуживания та же, что у сторожа доступности (health-watch.off):
# во время обновления временная база рядом с рабочей не нужна.
set -euo pipefail
cd "$(dirname "$0")"
REPO="$(pwd)"
TRIGGER_DIR="${OPS_TRIGGER_DIR:-$REPO/ops-triggers}"
REQUEST="$TRIGGER_DIR/restore-check.request"
RESULT="$TRIGGER_DIR/restore-check.result"
LOCK="$TRIGGER_DIR/restore-check.lock"
LOG="$TRIGGER_DIR/restore-check.log"
OFF_FILE="$TRIGGER_DIR/health-watch.off"
DAYS="${RESTORE_CHECK_DAYS:-30}"
HOUR="${RESTORE_CHECK_HOUR:-04}"
NOW="${RESTORE_CHECK_NOW:-$(date +%s)}"            # подменяется в тестах
CUR_HOUR="${RESTORE_CHECK_CUR_HOUR:-$(date +%H)}"   # подменяется в тестах

mkdir -p "$TRIGGER_DIR"
[ -f "$OFF_FILE" ] && exit 0
# Уже идёт — второй экземпляр снёс бы временную базу из-под первого.
[ -d "$LOCK" ] && exit 0

reason=""
if [ -f "$REQUEST" ]; then
  reason="по заявке"
else
  [ "$CUR_HOUR" = "$HOUR" ] || exit 0
  last=0
  [ -f "$RESULT" ] && last="$(stat -c %Y "$RESULT" 2>/dev/null || stat -f %m "$RESULT")"
  [ $((NOW - last)) -ge $((DAYS * 86400)) ] || exit 0
  # Есть ли годный набор новее последней проверки (db.dump без FAILED.txt).
  BACKUP_DIR="${BACKUP_DIR:-$({ grep -E '^BACKUP_DIR=' .env.prod 2>/dev/null | cut -d= -f2- | tail -1; } || true)}"
  BACKUP_DIR="${BACKUP_DIR:-$REPO/backups}"
  fresh=""
  for d in "$BACKUP_DIR"/*/; do
    [ -f "$d/db.dump" ] && [ ! -f "$d/FAILED.txt" ] || continue
    m="$(stat -c %Y "$d/db.dump" 2>/dev/null || stat -f %m "$d/db.dump")"
    [ "$m" -gt "$last" ] && fresh=1 && break
  done
  [ -n "$fresh" ] || exit 0
  reason="плановая (раз в $DAYS дн.)"
fi

rm -f "$REQUEST"
printf '%s запуск: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$reason" >> "$TRIGGER_DIR/restore-check.runs"
# setsid/nohup: проверка не должна умереть вместе с наблюдателем.
if command -v setsid >/dev/null 2>&1; then
  setsid nohup ./restore-check.sh >"$LOG" 2>&1 < /dev/null &
else
  nohup ./restore-check.sh >"$LOG" 2>&1 < /dev/null &
fi
exit 0
