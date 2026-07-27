# Генератор документации Dashboard (.docx с реальными скриншотами)

Пересобирает 5 документов в `docs/`: Паспорт системы, Установка и настройка,
Руководства администратора / модератора / пользователя.

## Предпосылки
- Запущенный dev-стек (`docker compose -p dashbord up -d`) и dev-фронт на :3080
  (vite), бэкенд на :8080; учётка `admin/admin`.
- Node 18+. Установка зависимостей (один раз):
  `npm install docx playwright docx-preview jszip --no-save && npx playwright install chromium`

## Порядок
1. `node shoot_all.js` — снимет ~35 скриншотов в `shots/` (сам создаёт и удаляет
   временные учётки ztest_mod/ztest_user и временный архив-слепок «Динамика МФЦ»).
2. `node doc_user.js && node doc_moderator.js && node doc_admin.js && node doc_install.js && node doc_passport.js`
   → готовые .docx в `out/`.
3. Проверка рендера: `node preview.js out/<файл>.docx имя` → PNG-страницы в `out/`.
4. Скопировать .docx в `../../docs/`, закоммитить, пересобрать архивы поставки
   (`git archive`).

Правило: документация обновляется в день изменения функционала.
