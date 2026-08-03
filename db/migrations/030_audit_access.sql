-- Волна B (ревизия 2026-07-31): грант доступа admin→аудит (выдаёт superadmin,
-- сам superadmin видит аудит всегда без гранта) + новое действие 'export'
-- (логирование выгрузок дашбордов в PDF/Excel/PNG для отчёта активности юзера).

alter type audit_action add value if not exists 'export';

create table if not exists audit_access_grants (
    user_id uuid primary key references users(id) on delete cascade,
    granted_by uuid references users(id) on delete set null,
    granted_at timestamptz not null default now()
);
