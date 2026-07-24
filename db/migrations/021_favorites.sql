-- 021: избранные дашборды пользователя (быстрый доступ для обычного пользователя).
create table if not exists dashboard_favorites (
    user_id      uuid not null references users(id) on delete cascade,
    dashboard_id uuid not null references dashboards(id) on delete cascade,
    created_at   timestamptz not null default now(),
    primary key (user_id, dashboard_id)
);
create index if not exists ix_dashboard_favorites_user on dashboard_favorites (user_id);
