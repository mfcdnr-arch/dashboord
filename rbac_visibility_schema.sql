-- =========================================================
-- RBAC как основной механизм видимости (вариант B)
-- Дополняет lifecycle_schema.sql. Заменяет access_policies из abac_dataset_release_fields.sql
-- для целей видимости; ABAC-таблицы остаются, но только для lineage/audit.
-- =========================================================

create type user_role_code as enum ('admin', 'moderator', 'analyst', 'viewer');

create table roles (
    id uuid primary key default gen_random_uuid(),
    code user_role_code not null unique,
    name text not null,
    can_edit_formulas boolean not null default false,   -- только admin (вопрос 7)
    can_moderate boolean not null default false,        -- только moderator
    can_build_dashboards boolean not null default false, -- admin + analyst
    can_upload_documents boolean not null default false  -- admin + moderator + analyst
);

insert into roles (code, name, can_edit_formulas, can_moderate, can_build_dashboards, can_upload_documents) values
    ('admin',     'Администратор', true,  false, true,  true),
    ('moderator', 'Модератор',      false, true,  false, true),
    ('analyst',   'Аналитик',       false, false, true,  true),
    ('viewer',    'Пользователь',   false, false, false, false);

create table user_roles (
    user_id uuid not null references users(id) on delete cascade,
    role_id uuid not null references roles(id) on delete cascade,
    assigned_by uuid not null references users(id),
    assigned_at timestamptz not null default now(),
    primary key (user_id, role_id)
);

-- Видимость только на уровне опубликованного дашборда целиком (вопрос 13)
create table dashboard_access_grants (
    id uuid primary key default gen_random_uuid(),
    dashboard_id uuid not null references dashboards(id) on delete cascade,
    grantee_type text not null check (grantee_type in ('role', 'user')),
    role_id uuid references roles(id),
    user_id uuid references users(id),
    granted_by uuid not null references users(id),
    granted_at timestamptz not null default now(),
    check (
        (grantee_type = 'role' and role_id is not null and user_id is null) or
        (grantee_type = 'user' and user_id is not null and role_id is null)
    )
);
create index ix_dashboard_access_grants_dashboard on dashboard_access_grants (dashboard_id);
create index ix_dashboard_access_grants_user on dashboard_access_grants (user_id) where user_id is not null;

-- admin и moderator видят все опубликованные дашборды без explicit grant — проверяется в коде сервиса, не в таблице

-- аутентификация: логин/пароль, без SSO/MFA (вопрос 1)
alter table users add column if not exists password_hash text;
alter table users add column if not exists password_set_by_admin_at timestamptz;
alter table users add column if not exists must_change_password boolean not null default false;

create table password_reset_requests (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references users(id) on delete cascade,
    reset_by_admin_id uuid not null references users(id),
    temporary_password_hash text not null,
    used boolean not null default false,
    created_at timestamptz not null default now()
);
