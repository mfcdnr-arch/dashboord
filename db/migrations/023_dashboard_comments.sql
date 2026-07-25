-- 023: Комментарии / обсуждение к дашбордам (лента).
--
-- Доступ к чтению и написанию наследует видимость дашборда (RLS _can_view):
-- кто видит дашборд — тот видит обсуждение и может оставить комментарий.
-- Удаление — автор комментария или привилегированная роль (проверяется в коде).
-- Идемпотентно.

create table if not exists dashboard_comments (
    id uuid primary key default gen_random_uuid(),
    dashboard_id uuid not null references dashboards(id) on delete cascade,
    user_id uuid references users(id) on delete set null,   -- null, если автор удалён
    body text not null,
    created_at timestamptz not null default now()
);

-- Лента страницей: новые сверху, диапазон по дашборду.
create index if not exists ix_dashboard_comments_dash
    on dashboard_comments (dashboard_id, created_at desc);
