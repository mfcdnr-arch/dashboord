-- =========================================================
-- 003 · Флаги ролей
-- Нужны модулю доступа (004_access_grants / rbac_v2) и модерации:
--   can_edit_formulas — роль может редактировать формулы метрик
--   can_moderate      — роль может одобрять/публиковать (проверка при approve)
-- =========================================================

alter table roles add column if not exists can_edit_formulas boolean not null default false;
alter table roles add column if not exists can_moderate boolean not null default false;
