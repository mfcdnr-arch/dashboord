-- 034: Витрины (волна E) — именованная подборка из N ЦЕЛЫХ дашбордов на одном
-- экране. НЕ путать с «📺 Витрина» (KioskView) — тот слайд-шоу СТРАНИЦ ОДНОГО
-- дашборда; здесь наоборот — несколько РАЗНЫХ дашбордов показаны одновременно.
-- Идемпотентно.

create table if not exists showcases (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    name text not null,
    created_by uuid references users(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index if not exists ix_showcases_org on showcases (organization_id, name);

create table if not exists showcase_items (
    id uuid primary key default gen_random_uuid(),
    showcase_id uuid not null references showcases(id) on delete cascade,
    dashboard_id uuid not null references dashboards(id) on delete cascade,
    position integer not null default 0,
    created_at timestamptz not null default now(),
    unique (showcase_id, dashboard_id)
);
create index if not exists ix_showcase_items_showcase on showcase_items (showcase_id, position);
