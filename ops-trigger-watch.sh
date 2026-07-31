#!/usr/bin/env bash
# Наблюдатель файла-триггера от API («Запустить сейчас» в UI → «Настройки» /
# «Отчёты»). Backend (в контейнере, без доступа к docker.sock) кладёт файл
# ops-triggers/backup.request на общий том; этот скрипт — запускается ЧАСТО
# хостовым cron/systemd (см. backup-schedule.sh, устанавливается вместе с
# ежедневным расписанием) — видит его, гонит обычный backup.sh и пишет
# результат обратно в ops-triggers/backup.result, откуда его читает API
# (GET /maintenance/backup/status) для UI.
set -euo pipefail
cd "$(dirname "$0")"
REPO="$(pwd)"
TRIGGER_DIR="${OPS_TRIGGER_DIR:-$REPO/ops-triggers}"
REQUEST="$TRIGGER_DIR/backup.request"
RESULT="$TRIGGER_DIR/backup.result"
LOG="$TRIGGER_DIR/backup.request.log"

# Нет заявки — обычный случай при каждом запуске (раз в минуту), не ошибка.
[ -f "$REQUEST" ] || exit 0

mkdir -p "$TRIGGER_DIR"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"  # переносимо (GNU/BSD date), не -Is (только GNU)
if ./backup.sh >"$LOG" 2>&1; then
  printf '{"ts":"%s","ok":true,"message":"Бэкап выполнен успешно"}\n' "$TS" > "$RESULT"
else
  printf '{"ts":"%s","ok":false,"message":"Бэкап завершился с ошибкой — см. ops-triggers/backup.request.log"}\n' "$TS" > "$RESULT"
fi
rm -f "$REQUEST"
