-- =========================================================
-- 016 · Отделы (справочник) + раздельные ФИО у пользователей (волна B)
-- Модуль «Пользователи»: заведение из UI (было только через SQL).
-- =========================================================

create table if not exists departments (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    name text not null,
    created_at timestamptz not null default now(),
    unique (organization_id, name)
);
create index if not exists ix_departments_org on departments (organization_id);

-- Раздельные ФИО (full_name оставлен для совместимости; собирается из частей)
alter table users add column if not exists last_name text;
alter table users add column if not exists first_name text;
alter table users add column if not exists middle_name text;
alter table users add column if not exists department_id uuid references departments(id) on delete set null;
