#!/usr/bin/env bash
# Ежедневный полный архив проекта Dashboard (все файлы и документы) с меткой даты/времени.
# Складывается ВНЕ репозитория, чтобы не раздувать рабочую копию и не попадать в git.
set -euo pipefail

SRC_DIR="/Users/denis/Dashbord"
SRC_PARENT="$(dirname "$SRC_DIR")"
SRC_NAME="$(basename "$SRC_DIR")"
DEST_DIR="/Users/denis/Dashbord-archives"
RETENTION_DAYS=14

TS="$(date +%Y-%m-%d_%H-%M-%S)"
ARCHIVE_PATH="${DEST_DIR}/dashbord-project_${TS}.tar.gz"
LOG_FILE="${DEST_DIR}/archive.log"

mkdir -p "$DEST_DIR"

tar -czf "$ARCHIVE_PATH" \
  -C "$SRC_PARENT" \
  --exclude "${SRC_NAME}/.DS_Store" \
  --exclude "${SRC_NAME}/**/.DS_Store" \
  --exclude "${SRC_NAME}/**/node_modules" \
  --exclude "${SRC_NAME}/**/__pycache__" \
  --exclude "${SRC_NAME}/**/.venv" \
  --exclude "${SRC_NAME}/**/venv" \
  --exclude "${SRC_NAME}/**/dist" \
  --exclude "${SRC_NAME}/**/build" \
  --exclude "${SRC_NAME}/**/.vite" \
  --exclude "${SRC_NAME}/dashbord-images.tar" \
  --exclude "${SRC_NAME}/Final_v.1.tar" \
  --exclude "${SRC_NAME}/Final_v.1.zip" \
  --exclude "${SRC_NAME}/backups" \
  --exclude "${SRC_NAME}/certs" \
  --exclude "${SRC_NAME}/tmp" \
  --exclude "${SRC_NAME}/data" \
  --exclude "${SRC_NAME}/tools/docgen/out" \
  --exclude "${SRC_NAME}/tools/docgen/shots" \
  "$SRC_NAME"

SIZE="$(du -sh "$ARCHIVE_PATH" | cut -f1)"
echo "$(date '+%Y-%m-%d %H:%M:%S') OK  ${ARCHIVE_PATH}  (${SIZE})" >> "$LOG_FILE"

# Ротация: хранить архивы не старше RETENTION_DAYS дней
find "$DEST_DIR" -name 'dashbord-project_*.tar.gz' -mtime "+${RETENTION_DAYS}" -delete

echo "Архив создан: ${ARCHIVE_PATH} (${SIZE})"
