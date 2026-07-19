-- =========================================================
-- 017 · Аудит входов (волна B): журнал попыток входа
-- Пишется на каждый /auth/login (успех и неуспех): кто/когда/IP/агент.
-- =========================================================

create table if not exists login_events (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid references organizations(id) on delete cascade,
    user_id uuid references users(id) on delete set null,
    login text,                     -- введённый логин (в т.ч. несуществующий при неудаче)
    ip text,
    user_agent text,
    success boolean not null default false,
    created_at timestamptz not null default now()
);

create index if not exists ix_login_events_created on login_events (created_at desc);
create index if not exists ix_login_events_user on login_events (user_id);
create index if not exists ix_login_events_org on login_events (organization_id);
