-- 026_org_setup.sql
-- Признак завершения первичной настройки НА УРОВНЕ ОРГАНИЗАЦИИ (серверный флаг),
-- чтобы мастер настройки не всплывал повторно при смене браузера/устройства
-- (раньше было только в localStorage). Идемпотентно.

alter table organizations add column if not exists setup_dismissed boolean not null default false;
