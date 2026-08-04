-- =========================================================
-- ABAC тегирование на уровне dataset_release_fields
-- Дополняет lifecycle_schema.sql
-- =========================================================

create type attribute_scope as enum ('field', 'dataset_release', 'metric', 'widget', 'dashboard');
create type policy_effect as enum ('allow', 'deny');

-- Словарь атрибутов (справочник тегов)
create table attribute_definitions (
    id uuid primary key default gen_random_uuid(),
    code text not null unique,          -- sensitivity, department, region, source_trust, data_category
    name text not null,
    value_type text not null default 'text',
    allowed_values text[],              -- если замкнутый список, null = свободный текст
    created_at timestamptz not null default now()
);

-- Навешивание тегов на dataset_release_fields (и другие сущности через scope+object_id)
create table attribute_assignments (
    id uuid primary key default gen_random_uuid(),
    scope attribute_scope not null,
    object_id uuid not null,            -- FK логически на dataset_release_fields.id / metrics.id / widgets.id / dashboards.id
    attribute_id uuid not null references attribute_definitions(id) on delete cascade,
    attribute_value text not null,
    assigned_by uuid not null references users(id),
    created_at timestamptz not null default now(),
    unique (scope, object_id, attribute_id)
);
create index ix_attribute_assignments_object on attribute_assignments (scope, object_id);
create index ix_attribute_assignments_value on attribute_assignments (attribute_id, attribute_value);

-- Политики доступа: правило = комбинация атрибутов субъекта (роль/отдел/регион) и атрибутов объекта
create table access_policies (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    name text not null,
    effect policy_effect not null default 'allow',
    priority integer not null default 100,   -- меньше = выше приоритет, deny всегда биет allow при равном приоритете
    subject_condition jsonb not null,        -- {"role": "analyst"} или {"department": "finance"}
    object_condition jsonb not null,         -- {"sensitivity": "confidential"} или {"region": "eu"}
    scope attribute_scope not null,
    is_active boolean not null default true,
    created_by uuid not null references users(id),
    created_at timestamptz not null default now()
);
create index ix_access_policies_scope on access_policies (organization_id, scope, is_active);

-- Кеш решения (для аудита и быстрого повторного доступа; TTL через Redis на практике)
create table access_decisions_log (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references users(id),
    scope attribute_scope not null,
    object_id uuid not null,
    decision policy_effect not null,
    matched_policy_id uuid references access_policies(id),
    evaluated_at timestamptz not null default now()
);
create index ix_access_decisions_log_user on access_decisions_log (user_id, evaluated_at desc);
