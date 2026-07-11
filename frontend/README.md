# Dashboard Frontend (React + TypeScript + Vite)

Каркас интерфейса: две зоны (Панель управления + Viewer). Пока — заглушки + индикатор
состояния API (`/health`).

## Требуется
Node.js 20+ (LTS).

## Запуск (dev)
```bash
cd frontend
npm install
npm run dev        # http://localhost:3080
```
Запросы `/health`, `/system` проксируются на API (`http://localhost:8080`) — см. `vite.config.ts`.
Для полной картины параллельно должен работать бэкенд (uvicorn на 8080 или контейнер `api`).

## Сборка
```bash
npm run build      # результат в dist/
```
