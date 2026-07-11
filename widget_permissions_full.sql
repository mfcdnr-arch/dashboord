-- =========================================================
-- Система дашбордов: наследование прав, уведомления, аудит
-- PostgreSQL 16+ / готово для TypeORM/Prisma под NestJS
-- =========================================================

create extension if not exists pgcrypto;

-- ---------- ENUM типы ----------
create type access_subject_type as enum ('user', 'role');
create type securable_type as enum ('folder', 'dashboard', 'widget');
create type permission_effect as enum ('allow', 'deny');
create type publication_status as enum ('draft', 'review', 'published', 'archived');
create type notification_status as enum ('pending', 'sent', 'failed', 'ignored');
create type audit_action as enum ('create', 'update', 'delete', 'publish', 'grant_access', 'revoke_access', 'view');

-- ---------- Базовые сущности ----------
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

-- ---------- Слой наследования прав ----------
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

-- ---------- Уведомления ----------
create table notification_events (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    event_type text not null,
    entity_type text not null,
    entity_id uuid not null,
    payload jsonb not null default '{}'::jsonb,
    status notification_status not null default 'pending',
    created_at timestamptz not null default now(),
    processed_at timestamptz
);

create table notification_recipients (
    id uuid primary key default gen_random_uuid(),
    notification_event_id uuid not null references notification_events(id) on delete cascade,
    user_id uuid not null references users(id) on delete cascade,
    is_read boolean not null default false,
    read_at timestamptz,
    created_at timestamptz not null default now(),
    unique (notification_event_id, user_id)
);

-- ---------- Аудит ----------
create table audit_log (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    actor_user_id uuid references users(id) on delete set null,
    action audit_action not null,
    entity_type text not null,
    entity_id uuid not null,
    old_data jsonb,
    new_data jsonb,
    ip_address text,
    created_at timestamptz not null default now()
);

create index ix_audit_log_entity on audit_log (entity_type, entity_id, created_at desc);
create index ix_audit_log_actor on audit_log (actor_user_id, created_at desc);

insert into permissions (code, name, description) values
('dashboard.view', 'Просмотр дашборда', 'Разрешает видеть дашборд'),
('dashboard.edit', 'Редактирование дашборда', 'Разрешает редактировать структуру дашборда'),
('dashboard.publish', 'Публикация дашборда', 'Разрешает отправлять и публиковать дашборд'),
('widget.view', 'Просмотр виджета', 'Разрешает видеть конкретный виджет внутри дашборда'),
('widget.edit', 'Редактирование виджета', 'Разрешает изменять конфигурацию виджета'),
('folder.view', 'Просмотр папки', 'Разрешает видеть папку и связанные с ней объекты');

-- =========================================================
-- Функция рекурсивного разрешения доступа с учётом наследования
-- =========================================================
create or replace function fn_resolve_access(
    p_user_id uuid,
    p_securable_id uuid,
    p_permission_code text
) returns boolean as $$
declare
    v_permission_id uuid;
    v_result boolean;
begin
    select id into v_permission_id from permissions where code = p_permission_code;
    if v_permission_id is null then
        return false;
    end if;

    with recursive chain as (
        select so.id as securable_id, so.parent_securable_id, so.inherit_permissions, 0 as depth
        from securable_objects so
        where so.id = p_securable_id
        union all
        select so.id, so.parent_securable_id, so.inherit_permissions, c.depth + 1
        from securable_objects so
        join chain c on so.id = c.parent_securable_id
        where c.inherit_permissions = true
    ),
    subject_ids as (
        select p_user_id as subject_id, 'user'::access_subject_type as subject_type
        union all
        select ur.role_id, 'role'::access_subject_type
        from user_roles ur
        where ur.user_id = p_user_id
    ),
    matched as (
        select oa.effect, c.depth
        from object_acl oa
        join chain c on oa.securable_id = c.securable_id
        join subject_ids s on oa.subject_type = s.subject_type and oa.subject_id = s.subject_id
        where oa.permission_id = v_permission_id
          and (oa.valid_from is null or oa.valid_from <= now())
          and (oa.valid_to is null or oa.valid_to >= now())
    )
    select
        case
            when exists (select 1 from matched where effect = 'deny') then false
            when exists (select 1 from matched where effect = 'allow') then true
            else false
        end
    into v_result;

    insert into access_resolution_cache (user_id, securable_id, permission_id, is_allowed, resolved_at)
    values (p_user_id, p_securable_id, v_permission_id, coalesce(v_result, false), now())
    on conflict (user_id, securable_id, permission_id)
    do update set is_allowed = excluded.is_allowed, resolved_at = excluded.resolved_at;

    return coalesce(v_result, false);
end;
$$ language plpgsql;

-- =========================================================
-- Автосоздание securable_objects для новых папок/дашбордов/виджетов
-- =========================================================
create or replace function fn_create_securable_for_folder() returns trigger as $$
begin
    insert into securable_objects (organization_id, object_type, object_id, parent_securable_id, inherit_permissions)
    values (
        new.organization_id, 'folder', new.id,
        (select id from securable_objects where object_type = 'folder' and object_id = new.parent_folder_id),
        true
    );
    return new;
end;
$$ language plpgsql;

create trigger trg_folder_securable
    after insert on folders
    for each row execute function fn_create_securable_for_folder();

create or replace function fn_create_securable_for_dashboard() returns trigger as $$
begin
    insert into securable_objects (organization_id, object_type, object_id, parent_securable_id, inherit_permissions)
    values (
        new.organization_id, 'dashboard', new.id,
        (select id from securable_objects where object_type = 'folder' and object_id = new.folder_id),
        true
    );
    return new;
end;
$$ language plpgsql;

create trigger trg_dashboard_securable
    after insert on dashboards
    for each row execute function fn_create_securable_for_dashboard();

-- =========================================================
-- Автосоздание securable_objects + уведомление о новом виджете без прав
-- =========================================================
create or replace function fn_create_securable_for_widget() returns trigger as $$
declare
    v_dashboard_securable_id uuid;
    v_org_id uuid;
    v_event_id uuid;
begin
    select id, organization_id into v_dashboard_securable_id, v_org_id
    from securable_objects
    where object_type = 'dashboard' and object_id = new.dashboard_id;

    insert into securable_objects (organization_id, object_type, object_id, parent_securable_id, inherit_permissions)
    values (new.organization_id, 'widget', new.id, v_dashboard_securable_id, true);

    insert into notification_events (organization_id, event_type, entity_type, entity_id, payload)
    values (
        new.organization_id,
        'widget.created.no_explicit_access',
        'widget',
        new.id,
        jsonb_build_object('widget_name', new.name, 'dashboard_id', new.dashboard_id)
    )
    returning id into v_event_id;

    insert into notification_recipients (notification_event_id, user_id)
    select v_event_id, u.id
    from users u
    join user_roles ur on ur.user_id = u.id
    join role_permissions rp on rp.role_id = ur.role_id
    join permissions p on p.id = rp.permission_id
    where p.code = 'dashboard.publish'
      and u.organization_id = new.organization_id;

    return new;
end;
$$ language plpgsql;

create trigger trg_widget_securable
    after insert on widgets
    for each row execute function fn_create_securable_for_widget();

-- =========================================================
-- Аудит изменений widgets, dashboards, object_acl
-- =========================================================
create or replace function fn_audit_generic() returns trigger as $$
declare
    v_org_id uuid;
    v_action audit_action;
begin
    if tg_op = 'INSERT' then
        v_action := 'create';
    elsif tg_op = 'UPDATE' then
        v_action := 'update';
    elsif tg_op = 'DELETE' then
        v_action := 'delete';
    end if;

    v_org_id := coalesce(
        (case when tg_op = 'DELETE' then old.organization_id else new.organization_id end),
        null
    );

    insert into audit_log (organization_id, actor_user_id, action, entity_type, entity_id, old_data, new_data)
    values (
        v_org_id,
        nullif(current_setting('app.current_user_id', true), '')::uuid,
        v_action,
        tg_argv[0],
        case when tg_op = 'DELETE' then old.id else new.id end,
        case when tg_op in ('UPDATE','DELETE') then to_jsonb(old) else null end,
        case when tg_op in ('UPDATE','INSERT') then to_jsonb(new) else null end
    );

    if tg_op = 'DELETE' then
        return old;
    end if;
    return new;
end;
$$ language plpgsql;

create trigger trg_audit_widgets
    after insert or update or delete on widgets
    for each row execute function fn_audit_generic('widget');

create trigger trg_audit_dashboards
    after insert or update or delete on dashboards
    for each row execute function fn_audit_generic('dashboard');

create trigger trg_audit_object_acl
    after insert or update or delete on object_acl
    for each row execute function fn_audit_generic('object_acl');

-- =========================================================
-- Инвалидация кэша разрешений при изменении ACL
-- =========================================================
create or replace function fn_invalidate_access_cache() returns trigger as $$
begin
    delete from access_resolution_cache
    where securable_id = coalesce(new.securable_id, old.securable_id);
    return coalesce(new, old);
end;
$$ language plpgsql;

create trigger trg_invalidate_cache_on_acl_change
    after insert or update or delete on object_acl
    for each row execute function fn_invalidate_access_cache();

-- Представление дерева объектов и наследования
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
