-- 050. Быстрый доступ: меню коротких названий отчётов («MAX», «КЭП», «Статистика
-- отделов»…), собираемое администратором из уже распознанных форм/дашбордов.
--
-- Отдельная таблица, а не поле на dashboards: пункт меню может указывать не
-- только на дашборд, но и на bespoke-раздел (dnr_stats, витрины) — того, чему
-- в dashboards соответствовать нечему. Видимость каждого пункта проверяется
-- при чтении (RLS дашборда / гейт раздела), а не хранится здесь — иначе
-- список для разных пользователей пришлось бы держать отдельными строками.

create table if not exists quick_links (
    id              uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    label           text not null,
    kind            text not null check (kind in ('dashboard', 'section')),
    dashboard_id    uuid references dashboards(id) on delete cascade,
    section         text,
    position        integer not null default 0,
    created_by      uuid references users(id),
    created_at      timestamptz not null default now(),
    check (
        (kind = 'dashboard' and dashboard_id is not null and section is null) or
        (kind = 'section' and section is not null and dashboard_id is null)
    )
);

create index if not exists ix_quick_links_org on quick_links (organization_id, position);

comment on table quick_links is
    'Куратор-меню коротких названий отчётов на быстрый доступ (сайдбар, все роли) — «MAX», «КЭП» и т.п.';
