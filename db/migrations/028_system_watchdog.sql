-- Автопочинка по расписанию (arq cron) + история heal-действий (ручных и авто).
-- Системная таблица (не org-scoped): бакет MinIO/Redis — общая инфраструктура
-- инсталляции, а не данные конкретной организации.

create table system_heal_log (
    id uuid primary key default gen_random_uuid(),
    triggered_by text not null check (triggered_by in ('manual', 'auto')),
    triggered_by_user_id uuid references users(id) on delete set null,
    status_before text not null,
    status_after text not null,
    healthy boolean not null,
    actions jsonb not null,
    created_at timestamptz not null default now()
);

create index ix_system_heal_log_created on system_heal_log (created_at desc);

-- Новое действие аудита (enum audit_action) — ручная починка, инициированная админом.
alter type audit_action add value if not exists 'heal';
