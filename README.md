# Dashboard (`dashbord`) — корпоративная BI-платформа

Система дашбордов с административной панелью для ГБУ «МФЦ ДНР»: загрузка
первичных документов (Excel/CSV/PDF/Word) → распознавание таблиц и разметка
листа «как в Excel» → выпуск датасетов → метрики с прозрачными формулами
(готовые рецепты и предложения из анализа самого файла) → дашборды с 17 типами
виджетов → модерация публикации → экспорт (Excel/PDF/PNG), архив и витрины.

Целевая среда: **Astra Linux SE / ВМ / LAN, часто офлайн**. Всё разворачивается
локально, без внешних SaaS.

---

## Быстрый старт (сервер)

```bash
tar -xf Final_v.1.tar && cd Dashbord && ./install.sh
```

Одна команда: проверит Docker, загрузит офлайн-бандл образов (если `dashbord-images.tar`
лежит рядом) либо соберёт образы, сгенерирует секреты, выпустит TLS-сертификат,
накатит миграции, поднимет стек и прогонит smoke-проверку.

Дальше: `https://<адрес-сервера>:8443/`, вход `superadmin` с временным паролем из
вывода установки (система потребует сменить его при первом входе).

Подробно — **[docs/Развертывание_на_сервере.md](docs/Развертывание_на_сервере.md)**
(шаг за шагом, онлайн и офлайн) и **[docs/ДЕПЛОЙ.md](docs/ДЕПЛОЙ.md)** (состав
стека, миграции, обновление, диагностика).

## Локальная разработка

```bash
docker compose -p dashbord up -d          # postgres:55432, redis:6380, minio:9800
sh db/run-migrations.sh                   # миграции с трекингом
scripts/dev-api.sh                        # API → http://127.0.0.1:8080
cd frontend && npm ci && npm run dev       # SPA → http://localhost:3080
```

Проверки перед коммитом:

```bash
cd backend && ruff check . && mypy && python -m pytest -q
cd frontend && npx tsc --noEmit && npm test && npm run build
```

## Архитектура (кратко)

| Слой | Технологии |
|---|---|
| Frontend | React 18 + TypeScript + Vite, ECharts, react-grid-layout; отдаётся nginx, он же прокси API |
| Backend | Python 3.12, FastAPI, asyncpg (без ORM — явный SQL), JWT (bcrypt) |
| Данные | PostgreSQL 16 (32 миграции), Redis (кэш + очередь arq), MinIO (файлы документов) |
| Фон | arq-воркер: распознавание документов, cron — свежесть данных, ретенция, автоархив, сторожевой health-watchdog |
| Наблюдаемость | Prometheus + Grafana + Loki (опциональный оверлей `--monitoring`), `/internal/metrics` |

Наружу открыт только веб-порт (nginx). PostgreSQL/Redis/MinIO — во внутренней
сети Docker.

## Структура репозитория

| Путь | Что внутри |
|---|---|
| `backend/app/modules/<домен>/` | модули API: `auth`, `objects`, `documents`, `ingestion`, `metrics`, `dashboards`, `moderation`, `reports`, `users`, `audit`, `appeals`, `showcases`, `catalog`, `maintenance`, `system`, `notifications`, `home` |
| `backend/tests/` | интеграционные тесты (pytest + httpx против ASGI, реальная БД) |
| `frontend/src/` | SPA: `components/` (экраны), `api/` (клиент), `theme.css` (3 темы) |
| `db/migrations/` | SQL-миграции `NNN_*.sql`, применяются раннером с трекингом |
| `docs/` | документация (см. ниже) |
| `monitoring/` | конфиги Prometheus/Grafana/Loki/promtail |
| `tools/docgen/` | генератор .docx-руководств со скриншотами |
| `*.sh` в корне | `install.sh`, `deploy.sh`, `smoke.sh`, `backup.sh`, `restore.sh`, `gen-secrets.sh`, `gen-tls.sh`, `diag.sh` |

## Документация

| Документ | Для кого |
|---|---|
| [docs/Развертывание_на_сервере.md](docs/Развертывание_на_сервере.md) | администратор сервера: установка шаг за шагом |
| [docs/ДЕПЛОЙ.md](docs/ДЕПЛОЙ.md) | эксплуатация: состав стека, обновление, бэкап, диагностика |
| [docs/Руководство_администратора.md](docs/Руководство_администратора.md) | роли, разграничение доступа, отложенные функции |
| [docs/Инструкция_по_формулам.md](docs/Инструкция_по_формулам.md) | модератор/аналитик: DSL формул метрик |
| [docs/requirements.md](docs/requirements.md) | полное ТЗ и журнал реализации |
| `docs/*.docx` | иллюстрированные руководства (администратор/модератор/пользователь), паспорт системы, установка |
| [CLAUDE.md](CLAUDE.md) | правила ведения проекта + журнал изменений |

## Лицензия и статус

Внутренняя разработка для ГБУ «МФЦ ДНР». Первое внедрение — на сервере
организации; см. журнал изменений в [CLAUDE.md](CLAUDE.md).
