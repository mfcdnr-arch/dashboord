# Dashboard API (FastAPI)

Модульная архитектура: каждый домен — отдельный пакет `app/modules/<name>/` со своим `router`.

## Планируемые модули
`auth` · `access` · `objects` · `ingestion` · `metrics` · `dashboards` ·
`moderation` · `viewer` · `archive` · `reports` · `admin` · `notifications` · `audit`

Сейчас реализован скелет: `system` (служебная информация) + `/health`.

## Запуск локально (без Docker)
Требуется работающий `dashbord_postgres` (порт 55432).

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
POSTGRES_HOST=localhost POSTGRES_PORT=55432 MINIO_ENDPOINT=localhost:9800 \
  uvicorn app.main:app --reload --port 8080
```

> Важно: `MINIO_ENDPOINT=localhost:9800` обязателен при локальном запуске — на старте
> приложение создаёт bucket в MinIO. Без переопределения оно пойдёт по Docker-имени
> `minio:9000`, которое вне контейнера не резолвится, и старт упадёт.

Проверка: `http://localhost:8080/health`, документация: `http://localhost:8080/docs`.

## Запуск в Docker
```bash
docker compose -p dashbord up -d api
```
Внутри сети Docker API ходит в БД по хосту `postgres:5432`.
