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

# Сохраняем КАЖДЫЙ образ в свой tar, затем упаковываем всё в один архив.
# Почему по одному: объединённый `docker save img1 img2 …` на некоторых стеках
# (Docker Desktop с containerd-store, смешанные платформы) падает с «content
# digest not found»; одиночный save работает везде. Один итоговый файл — удобно
# копировать на изолированную ВМ.
log "Сохранение образов (по одному) → $OUT…"
IMAGES="dashbord-api:latest dashbord-web:latest $POSTGRES_IMAGE $REDIS_IMAGE $MINIO_IMAGE"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
i=0
for img in $IMAGES; do
  i=$((i + 1))
  safe="$(printf '%02d_%s' "$i" "$img" | tr '/:' '__')"
  docker save -o "$TMP/${safe}.tar" "$img"
done
# Список образов для человека + автозагрузчик на целевой машине.
printf '%s\n' $IMAGES > "$TMP/IMAGES.txt"
cat > "$TMP/load.sh" <<'LOADER'
#!/usr/bin/env sh
# Загрузка образов из офлайн-бандла на целевой машине (Astra):
#   tar -xf dashbord-images.tar && sh load.sh
set -e
for t in [0-9][0-9]_*.tar; do echo "load $t"; docker load -i "$t"; done
echo "Готово. Образы загружены."
LOADER
tar -cf "$OUT" -C "$TMP" .

# Пост-проверка целостности: архив не пуст и содержит все per-image tar'ы.
log "Проверка бандла…"
[ -s "$OUT" ] || { echo "[bundle] ОШИБКА: пустой архив $OUT"; exit 1; }
n_tar="$(tar -tf "$OUT" | grep -c '\.tar$' || true)"
n_img="$(printf '%s\n' $IMAGES | wc -w | tr -d ' ')"
echo "  образов в бандле: $n_tar из $n_img"
tar -xOf "$OUT" ./IMAGES.txt 2>/dev/null | sed 's/^/  • /'
[ "$n_tar" = "$n_img" ] || { echo "[bundle] ОШИБКА: не все образы попали в бандл"; exit 1; }

log "Готово: $OUT ($(du -h "$OUT" | cut -f1)). На цели: tar -xf $(basename "$OUT") && sh load.sh"
