#!/usr/bin/env bash
# Офлайн-бандл образов для переноса на изолированную ВМ (Astra x86-64).
# Собирает api/web ПОД amd64 (независимо от арх. этой машины) и сохраняет все
# нужные образы в один tar. На целевой ВМ:  docker load -i dashbord-images.tar
#
#   ./bundle-images.sh            # → dashbord-images.tar
#   OUT=/path/bundle.tar ./bundle-images.sh
set -euo pipefail
cd "$(dirname "$0")"

PLATFORM="${PLATFORM:-linux/amd64}"
OUT="${OUT:-dashbord-images.tar}"

# Пины берём из .env.prod, иначе — дефолты (синхронно с docker-compose.prod.yml).
env_get() { grep -E "^$1=" .env.prod 2>/dev/null | cut -d= -f2- | tail -1; }
POSTGRES_IMAGE="${POSTGRES_IMAGE:-$(env_get POSTGRES_IMAGE)}"; POSTGRES_IMAGE="${POSTGRES_IMAGE:-postgres:16-alpine}"
REDIS_IMAGE="${REDIS_IMAGE:-$(env_get REDIS_IMAGE)}"; REDIS_IMAGE="${REDIS_IMAGE:-redis:7-alpine}"
MINIO_IMAGE="${MINIO_IMAGE:-$(env_get MINIO_IMAGE)}"; MINIO_IMAGE="${MINIO_IMAGE:-minio/minio:RELEASE.2022-10-24T18-35-07Z}"

log() { printf '\033[1;34m[bundle]\033[0m %s\n' "$1"; }

docker buildx version >/dev/null 2>&1 || { echo "нужен docker buildx (для сборки под $PLATFORM)"; exit 1; }

log "Сборка api/web под $PLATFORM (buildx --load)…"
docker buildx build --platform "$PLATFORM" -t dashbord-api:latest --load ./backend
docker buildx build --platform "$PLATFORM" -t dashbord-web:latest --load ./frontend

log "Загрузка базовых образов под $PLATFORM…"
for img in "$POSTGRES_IMAGE" "$REDIS_IMAGE" "$MINIO_IMAGE"; do
  docker pull --platform "$PLATFORM" "$img"
done

log "Сохранение в $OUT…"
docker save -o "$OUT" \
  dashbord-api:latest dashbord-web:latest \
  "$POSTGRES_IMAGE" "$REDIS_IMAGE" "$MINIO_IMAGE"

log "Готово: $OUT ($(du -h "$OUT" | cut -f1)). На цели: docker load -i $(basename "$OUT")"
