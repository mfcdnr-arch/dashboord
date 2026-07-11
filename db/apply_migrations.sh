#!/usr/bin/env bash
# Накат миграций Dashbord на работающий контейнер dashbord_postgres, по порядку.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/migrations" && pwd)"
DB="${POSTGRES_DB:-dashbord}"
USER="${POSTGRES_USER:-dashbord}"
for f in "$DIR"/*.sql; do
  echo "--- $(basename "$f") ---"
  docker exec -i dashbord_postgres psql -v ON_ERROR_STOP=1 -U "$USER" -d "$DB" < "$f"
done
echo "Миграции применены."
