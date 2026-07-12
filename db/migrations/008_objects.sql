-- =========================================================
-- 008 · Объекты
-- «Объект» — верхний организационный контейнер (раздел «Объекты» в панели).
-- Папки принадлежат объекту (folders.object_id). Контур доступа
-- (папка→дашборд→виджет) не меняется — объект это уровень группировки.
-- =========================================================

create table if not exists objects (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    name text not null,
    code text,
    description text,
    created_by uuid references users(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (organization_id, name)
);

alter table folders
    add column if not exists object_id uuid references objects(id) on delete set null;

create index if not exists ix_folders_object on folders (object_id);
