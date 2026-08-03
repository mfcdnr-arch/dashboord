-- 031: Обращения пользователей к администратору/модератору (волна C).
--
-- Лёгкий тред-чат «пользователь ↔ поддержка»: appeals — сама заявка (статус
-- open/answered/closed), appeal_messages — сообщения в ней (обе стороны).
-- Может быть создана и НЕАВТОРИЗОВАННО (заблокированный аккаунт не может
-- войти) — тогда sender_user_id у первого сообщения всё равно проставлен
-- (пользователь найден по логину на бэкенде), просто без JWT-сессии.
-- Идемпотентно.

create table if not exists appeals (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    user_id uuid not null references users(id) on delete cascade,
    subject text,
    status text not null default 'open' check (status in ('open', 'answered', 'closed')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Список «мои обращения»: по пользователю, свежие сверху.
create index if not exists ix_appeals_user on appeals (user_id, updated_at desc);
-- Список для staff: по организации (+ статус для фильтра «открытые»).
create index if not exists ix_appeals_org on appeals (organization_id, status, updated_at desc);

create table if not exists appeal_messages (
    id uuid primary key default gen_random_uuid(),
    appeal_id uuid not null references appeals(id) on delete cascade,
    sender_user_id uuid references users(id) on delete set null,
    is_staff boolean not null default false,
    body text not null,
    created_at timestamptz not null default now()
);

create index if not exists ix_appeal_messages_appeal on appeal_messages (appeal_id, created_at);
