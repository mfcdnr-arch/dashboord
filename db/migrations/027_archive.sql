-- 027: Архив дашбордов — слепки данных, месячные папки, избирательный доступ,
-- ежемесячная автоархивация.
--
-- Слепок (dashboard_archive.snapshot) хранит РАССЧИТАННЫЕ данные всех виджетов
-- на момент архивации: архив показывает «как было», даже если исходные данные
-- позже удалены ретенцией или дашборд удалён/изменён.

create table if not exists dashboard_archive (
    id               uuid primary key default gen_random_uuid(),
    organization_id  uuid not null references organizations(id),
    -- ссылка на живой дашборд; on delete set null — слепок переживает дашборд
    dashboard_id     uuid references dashboards(id) on delete set null,
    dashboard_name   text not null,
    topic            text,                          -- тема (рубрика) для поиска
    note             text,                          -- комментарий архиватора
    archive_month    text not null,                 -- 'YYYY-MM' — месячная папка
    snapshot         jsonb not null,                -- {pages:[{name, widgets:[…]}]}
    prev_status      text,                          -- статус дашборда до архивации
    auto             boolean not null default false,-- создан автоархивацией
    archived_at      timestamptz not null default now(),
    archived_by      uuid references users(id)
);

create index if not exists idx_archive_org_month on dashboard_archive(organization_id, archive_month, archived_at desc);
create index if not exists idx_archive_org_name  on dashboard_archive(organization_id, lower(dashboard_name));

-- Избирательный доступ пользователей к разделу «Архив» (admin/moderator видят всегда).
create table if not exists archive_access (
    organization_id  uuid not null references organizations(id),
    user_id          uuid not null references users(id) on delete cascade,
    granted_by       uuid references users(id),
    granted_at       timestamptz not null default now(),
    primary key (organization_id, user_id)
);

-- Флажок «📅 ежемесячный слепок в архив» на дашборде.
alter table dashboards add column if not exists auto_archive boolean not null default false;

-- Новые действия аудита (enum audit_action).
alter type audit_action add value if not exists 'archive';
alter type audit_action add value if not exists 'unarchive';
