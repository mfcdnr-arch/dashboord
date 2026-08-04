-- Схема БД для контроля прав на уровне виджетов в системе дашбордов
-- PostgreSQL 16+

create extension if not exists pgcrypto;

create type access_subject_type as enum ('user', 'role');
create type securable_type as enum ('folder', 'dashboard', 'widget');
create type permission_effect as enum ('allow', 'deny');
create type publication_status as enum ('draft', 'review', 'published', 'archived');

create table organizations (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    code text unique,
    created_at timestamptz not null default now()
);

create table users (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    login text not null,
    password_hash text not null,
    full_name text,
    email text,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    unique (organization_id, login)
);

create table roles (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    code text not null,
    name text not null,
    is_system boolean not null default false,
    created_at timestamptz not null default now(),
    unique (organization_id, code)
);

create table user_roles (
    user_id uuid not null references users(id) on delete cascade,
    role_id uuid not null references roles(id) on delete cascade,
    assigned_at timestamptz not null default now(),
    primary key (user_id, role_id)
);

create table folders (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    parent_folder_id uuid references folders(id) on delete set null,
    name text not null,
    code text,
    description text,
    created_by uuid references users(id),
    created_at timestamptz not null default now()
);

create table dashboards (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    folder_id uuid references folders(id) on delete set null,
    code text,
    name text not null,
    description text,
    publication_status publication_status not null default 'draft',
    version_no integer not null default 1,
    created_by uuid references users(id),
    published_by uuid references users(id),
    published_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table widgets (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    dashboard_id uuid not null references dashboards(id) on delete cascade,
    code text,
    name text not null,
    widget_type text not null,
    position_x integer not null default 0,
    position_y integer not null default 0,
    width integer not null default 4,
    height integer not null default 3,
    config jsonb not null default '{}'::jsonb,
    created_by uuid references users(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table dashboard_versions (
    id uuid primary key default gen_random_uuid(),
    dashboard_id uuid not null references dashboards(id) on delete cascade,
    version_no integer not null,
    snapshot jsonb not null,
    created_by uuid references users(id),
    created_at timestamptz not null default now(),
    unique (dashboard_id, version_no)
);

create table securable_objects (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    object_type securable_type not null,
    object_id uuid not null,
    parent_securable_id uuid references securable_objects(id) on delete cascade,
    inherit_permissions boolean not null default true,
    created_at timestamptz not null default now(),
    unique (object_type, object_id)
);

create table permissions (
    id uuid primary key default gen_random_uuid(),
    code text not null unique,
    name text not null,
    description text
);

create table role_permissions (
    role_id uuid not null references roles(id) on delete cascade,
    permission_id uuid not null references permissions(id) on delete cascade,
    primary key (role_id, permission_id)
);

create table object_acl (
    id uuid primary key default gen_random_uuid(),
    securable_id uuid not null references securable_objects(id) on delete cascade,
    subject_type access_subject_type not null,
    subject_id uuid not null,
    permission_id uuid not null references permissions(id) on delete cascade,
    effect permission_effect not null default 'allow',
    is_inherited boolean not null default false,
    granted_by uuid references users(id),
    granted_at timestamptz not null default now(),
    valid_from timestamptz,
    valid_to timestamptz,
    constraint chk_acl_valid_range check (valid_to is null or valid_from is null or valid_to >= valid_from)
);

create unique index ux_object_acl_rule
    on object_acl (securable_id, subject_type, subject_id, permission_id, effect)
    where is_inherited = false;

create index ix_object_acl_lookup
    on object_acl (subject_type, subject_id, permission_id, securable_id);

create table access_resolution_cache (
    user_id uuid not null references users(id) on delete cascade,
    securable_id uuid not null references securable_objects(id) on delete cascade,
    permission_id uuid not null references permissions(id) on delete cascade,
    is_allowed boolean not null,
    resolved_from_acl_id uuid references object_acl(id) on delete set null,
    resolved_at timestamptz not null default now(),
    primary key (user_id, securable_id, permission_id)
);

create table notification_events (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    event_type text not null,
    entity_type text not null,
    entity_id uuid not null,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    processed_at timestamptz
);

insert into permissions (code, name, description) values
('dashboard.view', 'Просмотр дашборда', 'Разрешает видеть дашборд'),
('dashboard.edit', 'Редактирование дашборда', 'Разрешает редактировать структуру дашборда'),
('dashboard.publish', 'Публикация дашборда', 'Разрешает отправлять и публиковать дашборд'),
('widget.view', 'Просмотр виджета', 'Разрешает видеть конкретный виджет внутри дашборда'),
('widget.edit', 'Редактирование виджета', 'Разрешает изменять конфигурацию виджета'),
('folder.view', 'Просмотр папки', 'Разрешает видеть папку и связанные с ней объекты');

create view v_securable_tree as
select
    so.id as securable_id,
    so.organization_id,
    so.object_type,
    so.object_id,
    so.parent_securable_id,
    so.inherit_permissions,
    case
        when so.object_type = 'folder' then f.name
        when so.object_type = 'dashboard' then d.name
        when so.object_type = 'widget' then w.name
    end as object_name
from securable_objects so
left join folders f on so.object_type = 'folder' and so.object_id = f.id
left join dashboards d on so.object_type = 'dashboard' and so.object_id = d.id
left join widgets w on so.object_type = 'widget' and so.object_id = w.id;
