---
name: ship-feature
description: Полный цикл выпуска доработки в проекте Dashboard (dashbord) — бэкенд+фронт, проверка (tsc/ast + e2e curl + браузер), очистка тестовых данных, build, журнал+память, коммит. Использовать при реализации любой новой фичи дашбордов (бэклог requirements.md §7, волны A/B из docs/Ревизия), чтобы не пропустить ни один шаг ритуала.
---

# Цикл разработки → проверки → выпуска фичи (Dashboard / dashbord)

Отвечать пользователю по-русски. Рабочая папка `/Users/denis/Dashbord`.
Стек: FastAPI (`backend/app/modules/<name>/`) + React (`frontend/src/`), PG/Redis/MinIO в docker-стеке `-p dashbord`.

Пройти шаги по порядку. Не объявлять «готово» без живой проверки.

## 1. Подготовка
- Отметить главу (mark_chapter) с коротким названием фичи.
- Прочитать затрагиваемый код: модуль `backend/app/modules/dashboards/{service.py,router.py}`, `frontend/src/components/DashboardsPage.tsx`, `frontend/src/api.ts`, при необходимости `WidgetView.tsx`, `home/`.

## 2. Реализация
- **Бэкенд:** логика в `service.py` (переиспользуемые функции, RLS через `_can_view`/`visible_dashboard_ids`), маршрут в `router.py`. Права: `manage = require_roles("admin","moderator")` на запись; чтение под RLS.
  - Новый КОРНЕВОЙ путь API → добавить в `frontend/vite.config.ts` proxy (цель `http://localhost:8080`). Вложенные под существующий префикс (`/dashboards/...`, `/widgets/...`) прокси не требуют.
  - Миграции — файл `db/migrations/NNN_*.sql`, идемпотентные (`create ... if not exists`); накат: `docker exec -i dashbord_postgres psql -v ON_ERROR_STOP=1 -U dashbord -d dashbord < db/migrations/NNN_*.sql`.
- **Фронт:** функции/типы в `api.ts`, UI в компоненте. Не перегружать (см. правило удобства для 4 ролей).

## 3. Статическая проверка
```
cd frontend && npx tsc --noEmit
cd backend  && python3 -c "import ast; ast.parse(open('app/modules/dashboards/service.py').read()); ast.parse(open('app/modules/dashboards/router.py').read())"
```

## 4. Поднять/перезапустить бэкенд
Одной командой (гасит прежний инстанс, ставит нужные env и порт 8080):
```
scripts/dev-api.sh          # запускать в фоне (run_in_background)
```
Фронт — через preview-инструмент: `preview_start {name:"frontend"}` (порт 3080, vite-прокси на :8080).

## 5. Сквозная проверка (e2e, curl)
Логин — форма (не JSON!):
```
TOKEN=$(curl -s -X POST http://127.0.0.1:8080/auth/login -d 'username=admin&password=admin' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
```
Дальше дёргать новые эндпоинты с `-H "Authorization: Bearer $TOKEN"`, проверять позитив и негатив (RLS→404, права→403, дубликат→400, неизвестный тип→400).

## 6. Проверка в браузере (обязательно)
- Открывать нужный экран. Если клики по координатам/ref не срабатывают (в этом приложении бывает) — кликать программно по тексту через `javascript_tool`:
  `[...document.querySelectorAll('button')].find(b=>b.textContent.includes('...')).click()`.
- Смотреть результат (screenshot), проверять `read_console_messages {onlyErrors:true}` — консоль должна быть чистой; для новых эндпоинтов — `read_network_requests`.

## 7. Очистка тестовых данных
Удалить всё, что создал для проверки (виджеты/дашборды/гранты/пресеты/пользователей). Вернуть БД в исходное состояние — снимать список «до» и удалять разницу. Никогда не оставлять тестовый мусор.

## 8. Продакшн-сборка
```
cd frontend && npm run build   # предупреждение про размер чанка — старое, игнор; ошибок быть не должно
```

## 9. Документация
- Дописать строку в журнал `docs/requirements.md` (что сделано + как проверено + СКВОЗНО/ВЖИВУЮ + tsc/build 0 + «что дальше»).
- Отметить пункт бэклога §7 / волны как ✅ (в `requirements.md` и/или `docs/Ревизия_2026-07-18.md`).

## 10. Память
Обновить `~/.Codex/projects/-Users-denis-Dashbord/memory/project_dashbord.md` (что готово + следующий шаг). Абсолютные даты, без дублей.

## 11. Коммит
Коммитить, только если пользователь просил (обычно после каждой фичи — да). Формат:
```
Дашборды <раздел>: <короткий заголовок>

<тело: что и зачем, ключевые файлы/эндпоинты>

Проверено сквозно+вживую: <итог>; консоль чистая, tsc/build 0.

Co-Authored-By: Codex Opus 4.8 <noreply@anthropic.com>
```

## 12. Ревью (правило пользователя)
После фичи — короткое профессиональное архитектурное ревью: что сделано, найденные слабые места/риски (честная самопроверка), предложения по улучшению. Оценивать удобство для 4 ролей (админ/модератор/аудит/пользователь) и три «максимума» (информативность/автоматизация/графичность).

Связанное: [[feedback_review_and_usability]], [[feedback_verify_and_document]], [[project_dashbord]]. Периодический аудит проекта — навык `/project-audit`.
