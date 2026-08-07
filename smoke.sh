#!/usr/bin/env bash
# Smoke-проверка развёрнутого стека. Проверяет через nginx (как реальный клиент):
#   1) /health → status ok, БД ok;  2) SPA (index.html) отдаётся;  3) API отвечает 401 без токена.
# Использование: ./smoke.sh [WEB_PORT] [SCHEME]   (по умолчанию 8090 http)
#   ./smoke.sh 8443 https   — проверка HTTPS (самоподписанный сертификат не проверяется).
set -euo pipefail
cd "$(dirname "$0")"
# HTTP-клиент: curl, а если его нет (базовая Astra) — python3. См. http-lib.sh.
. ./http-lib.sh

PORT="${1:-8090}"
SCHEME="${2:-http}"
BASE="${SCHEME}://localhost:${PORT}"
fail=0

if ! http_client_available; then
  echo "[smoke] ОШИБКА: нужен curl или python3 — нечем выполнить проверку." >&2
  exit 1
fi

check() { # описание; команда возвращает 0 при успехе
  if eval "$2" >/dev/null 2>&1; then
    printf '  \033[1;32m✓\033[0m %s\n' "$1"
  else
    printf '  \033[1;31m✗\033[0m %s\n' "$1"; fail=1
  fi
}

echo "[smoke] проверка $BASE"

# 1. /health через nginx → бэкенд; ожидаем "db":"ok"
check "/health отвечает и БД доступна" \
  "http_body '$BASE/health' 10 | grep -q '\"db\":\"ok\"'"

# 2. SPA отдаётся (index.html с корнем React)
check "SPA (index.html) отдаётся" \
  "http_body '$BASE/' 10 | grep -qi '<div id=\"root\"'"

# 3. Защищённый API без токена → 401 (значит auth-слой работает, а не отдаёт SPA)
check "API требует авторизацию (401 без токена)" \
  "[ \"\$(http_code '$BASE/dashboards' 10)\" = '401' ]"

if [ "$fail" = 0 ]; then
  echo "[smoke] ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ"; exit 0
else
  echo "[smoke] ЕСТЬ ПРОВАЛЫ"; exit 1
fi
