-- Графическое управление порогами (вместо правки .env + рестарт).
-- Системные пороги — один сервер на инсталляцию, поэтому синглтон-таблица
-- (не org-scoped): вход/блокировка, CPU/RAM/диск warn-crit для /reports/system.
create table system_settings (
    id smallint primary key default 1 check (id = 1),
    login_max_attempts int not null default 5,
    login_lockout_minutes int not null default 15,
    cpu_warn numeric not null default 70,
    cpu_crit numeric not null default 90,
    ram_warn numeric not null default 80,
    ram_crit numeric not null default 92,
    disk_warn numeric not null default 80,
    disk_crit numeric not null default 92,
    updated_at timestamptz not null default now(),
    updated_by uuid references users(id) on delete set null
);
insert into system_settings (id) values (1);

-- Org-scoped пороги (свежесть/ретенция уже считаются по организации).
alter table organizations add column if not exists settings jsonb not null default '{}'::jsonb;
