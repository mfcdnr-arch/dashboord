-- =========================================================
-- 014 · Шаблоны дашбордов
-- Библиотека переиспользуемых макетов: сохранить дашборд как шаблон и создавать
-- из него новые (клонирование = создание из шаблона, снятого с того же дашборда).
-- spec = снимок страниц+виджетов (как dashboard_versions.snapshot).
-- =========================================================
create table if not exists dashboard_templates (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    name text not null,
    description text,
    spec jsonb not null,
    created_by uuid references users(id),
    created_at timestamptz not null default now(),
    unique (organization_id, name)
);
create index if not exists ix_dashboard_templates_org on dashboard_templates (organization_id);
