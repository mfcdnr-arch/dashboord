-- =========================================================
-- 012 · Страницы дашбордов (этап 5)
-- Модель по пожеланиям заказчика: дашборд → именованные СТРАНИЦЫ → виджеты.
-- Страница = имя + описание + порядок; виджеты раскладываются на её сетке
-- (widgets.position_x/y/width/height уже есть). Виджет привязан к странице (page_id).
-- =========================================================

create table if not exists dashboard_pages (
    id uuid primary key default gen_random_uuid(),
    dashboard_id uuid not null references dashboards(id) on delete cascade,
    name text not null,
    description text,
    position integer not null default 0,   -- порядок страницы в дашборде
    created_by uuid references users(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (dashboard_id, name)
);

create index if not exists ix_dashboard_pages_dashboard on dashboard_pages (dashboard_id, position);

-- Виджет принадлежит странице (в дополнение к dashboard_id).
alter table widgets
    add column if not exists page_id uuid references dashboard_pages(id) on delete cascade;

create index if not exists ix_widgets_page on widgets (page_id);
