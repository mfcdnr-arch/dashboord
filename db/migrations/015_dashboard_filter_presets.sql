-- =========================================================
-- 015 · Пресеты фильтров дашборда (FR-13, бэклог §7)
-- Сохранённые наборы глобальных фильтров страницы (период + категория/строка).
-- Пресет привязан к дашборду и применяется к любой его странице.
-- =========================================================

create table if not exists dashboard_filter_presets (
    id uuid primary key default gen_random_uuid(),
    dashboard_id uuid not null references dashboards(id) on delete cascade,
    name text not null,
    filters jsonb not null default '{}'::jsonb,   -- {from, to, row}
    created_by uuid references users(id),
    created_at timestamptz not null default now(),
    unique (dashboard_id, name)
);

create index if not exists ix_dashboard_presets_dashboard on dashboard_filter_presets (dashboard_id);
