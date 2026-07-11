-- =========================================================
-- 007 · Авторизация
-- Флаг принудительной смены пароля (для первичного admin и сбросов).
-- =========================================================

alter table users add column if not exists must_change_password boolean not null default false;
