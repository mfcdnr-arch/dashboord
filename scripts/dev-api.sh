#!/usr/bin/env bash
# Локальный запуск API Dashboard (dashbord) с правильными env и портом.
# Порты соответствуют docker-стеку `-p dashbord` (PG 55432 / Redis 6380 / MinIO 9800).
# Перед стартом гасит предыдущий инстанс uvicorn (чтобы не ловить занятый порт).
#
# Использование:
#   scripts/dev-api.sh                 # запустить (foreground)
#   scripts/dev-api.sh --reload        # с автоперезагрузкой
# В Claude Code — запускать в фоне (run_in_background), логи смотреть отдельно.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"

if [ ! -x ".venv/bin/python" ]; then
  echo "Нет backend/.venv — создайте venv и установите зависимости." >&2
  exit 1
fi

# погасить прежний инстанс, если висит
pkill -f "uvicorn app.main:app" 2>/dev/null || true
sleep 1

export POSTGRES_HOST=localhost POSTGRES_PORT=55432
export REDIS_HOST=localhost REDIS_PORT=6380
export MINIO_ENDPOINT=localhost:9800

echo "API → http://127.0.0.1:8080  (PG:55432 Redis:6380 MinIO:9800)"
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 "$@"
