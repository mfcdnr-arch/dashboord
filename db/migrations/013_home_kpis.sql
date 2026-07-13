-- =========================================================
-- 013 · Ключевые KPI «Главной» (этап 5.5)
-- «Главная» — гибрид: базовые блоки фиксированы, а набор ключевых показателей
-- на главной выбирает администратор. Здесь храним этот выбор (метрики + порядок).
-- =========================================================

create table if not exists home_kpis (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    metric_code text not null,
    position integer not null default 0,
    created_by uuid references users(id),
    created_at timestamptz not null default now(),
    unique (organization_id, metric_code)
);

create index if not exists ix_home_kpis_org on home_kpis (organization_id, position);
