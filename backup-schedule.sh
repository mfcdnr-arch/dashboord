#!/usr/bin/env bash
# Планировщик автоматического бэкапа прод-стека Dashboard (обёртка над backup.sh).
# Ставит systemd-таймер (предпочтительно) либо cron-задачу (fallback).
#
#   sudo ./backup-schedule.sh install     # ежедневный бэкап (по умолч. 03:30)
#   sudo ./backup-schedule.sh status      # когда следующий запуск / последний результат
#   sudo ./backup-schedule.sh uninstall   # снять расписание
#   ./backup-schedule.sh print            # показать, что будет установлено (без прав)
#
# Настройка (env или .env.prod): BACKUP_TIME=HH:MM, BACKUP_KEEP=N, BACKUP_DIR=путь.
set -euo pipefail
cd "$(dirname "$0")"
REPO="$(pwd)"

env_get() { { grep -E "^$1=" .env.prod 2>/dev/null | cut -d= -f2- | tail -1; } || true; }
TIME="${BACKUP_TIME:-$(env_get BACKUP_TIME)}"; TIME="${TIME:-03:30}"
KEEP="${BACKUP_KEEP:-$(env_get BACKUP_KEEP)}"; KEEP="${KEEP:-7}"
BACKUP_DIR="${BACKUP_DIR:-$(env_get BACKUP_DIR)}"; BACKUP_DIR="${BACKUP_DIR:-$REPO/backups}"
SERVICE=dashbord-backup
ACTION="${1:-install}"

case "$TIME" in
  [0-2][0-9]:[0-5][0-9]) : ;;
  *) echo "BACKUP_TIME должно быть в формате HH:MM (получено '$TIME')"; exit 2 ;;
esac
HH="${TIME%%:*}"; MM="${TIME##*:}"

service_unit() {
  cat <<EOF
[Unit]
Description=Dashboard backup (pg_dump + MinIO tar + ротация)
After=docker.service
Wants=docker.service

[Service]
Type=oneshot
WorkingDirectory=$REPO
Environment=BACKUP_KEEP=$KEEP
Environment=BACKUP_DIR=$BACKUP_DIR
ExecStart=/usr/bin/env bash $REPO/backup.sh
EOF
}

timer_unit() {
  cat <<EOF
[Unit]
Description=Ежедневный бэкап Dashboard в $TIME

[Timer]
OnCalendar=*-*-* $TIME:00
Persistent=true

[Install]
WantedBy=timers.target
EOF
}

cron_line() {
  echo "$MM $HH * * * cd $REPO && BACKUP_KEEP=$KEEP BACKUP_DIR=$BACKUP_DIR ./backup.sh >> $BACKUP_DIR/cron.log 2>&1"
}

has_systemd() { command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; }
need_root() { [ "$(id -u)" = 0 ] || { echo "Нужны права root: sudo ./backup-schedule.sh $ACTION"; exit 1; }; }

case "$ACTION" in
  print)
    echo "# Расписание: ежедневно в $TIME, хранить $KEEP наборов, каталог $BACKUP_DIR"
    if has_systemd; then
      echo "# --- /etc/systemd/system/$SERVICE.service ---"; service_unit
      echo "# --- /etc/systemd/system/$SERVICE.timer ---"; timer_unit
    else
      echo "# --- crontab ---"; cron_line
    fi
    ;;
  install)
    need_root
    mkdir -p "$BACKUP_DIR"
    if has_systemd; then
      service_unit > "/etc/systemd/system/$SERVICE.service"
      timer_unit  > "/etc/systemd/system/$SERVICE.timer"
      systemctl daemon-reload
      systemctl enable --now "$SERVICE.timer"
      echo "systemd-таймер установлен:"; systemctl list-timers "$SERVICE.timer" --no-pager || true
    else
      ( crontab -l 2>/dev/null | grep -vF "$REPO/backup.sh"; cron_line ) | crontab -
      echo "cron-задача установлена:"; crontab -l | grep -F "$REPO/backup.sh"
    fi
    echo "Готово. Проверить разовый запуск: ./backup.sh"
    ;;
  uninstall)
    need_root
    if has_systemd && [ -f "/etc/systemd/system/$SERVICE.timer" ]; then
      systemctl disable --now "$SERVICE.timer" 2>/dev/null || true
      rm -f "/etc/systemd/system/$SERVICE.timer" "/etc/systemd/system/$SERVICE.service"
      systemctl daemon-reload
      echo "systemd-таймер снят."
    else
      crontab -l 2>/dev/null | grep -vF "$REPO/backup.sh" | crontab - || true
      echo "cron-задача снята."
    fi
    ;;
  status)
    if has_systemd && [ -f "/etc/systemd/system/$SERVICE.timer" ]; then
      systemctl list-timers "$SERVICE.timer" --no-pager || true
      echo "--- последний запуск ---"
      systemctl status "$SERVICE.service" --no-pager -n 5 2>/dev/null || true
    else
      echo "--- crontab ---"; crontab -l 2>/dev/null | grep -F "$REPO/backup.sh" || echo "(не установлено)"
    fi
    ;;
  *) echo "Использование: $0 {install|uninstall|status|print}"; exit 2 ;;
esac
