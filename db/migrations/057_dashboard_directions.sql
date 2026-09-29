-- Направления дашбордов (этап 3 «Предложения виджетов», решения заказчика 23.09.2026).
--
-- Направление — группа ВНУТРИ раздела «Дашборды» («РЦО», «МАХ», «Статистика
-- услуг»): в меню одна строка «Дашборды», а внутри дашборды разложены по
-- направлениям. У дашборда одно направление или никакого. Доступ прежний:
-- направление только группирует, кто видит какой дашборд, по-прежнему решают
-- гранты на дашборды.
--
-- Почему не папка дашборда (folder_id): папка — это папка ОБЪЕКТА, туда же
-- ложатся документы, и она — родитель дашборда в дереве прав
-- (securable_objects, 001_core.sql). Переиспользовать её под смысловую группу
-- значило бы сломать и наследование прав, и правило «объект = одна форма».
--
-- Чем отличается от остального «собрать вместе»: подборка «Руководителю» —
-- один флаг на всю организацию; витрины — M:N и показ нескольких дашбордов
-- на одном экране; быстрый доступ — ярлыки меню. Направление — РАЗБИЕНИЕ
-- всего списка на группы, 1 : 0..1.

create table if not exists dashboard_directions (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    name text not null check (length(btrim(name)) between 1 and 120),
    description text,
    -- Порядок групп в списке задаёт человек: первым должно идти главное
    -- направление, а не то, что раньше по алфавиту.
    position integer not null default 0,
    -- set null: удаление учётки не должно упираться в направления, которые
    -- она когда-то завела (иначе чистка тестовых пользователей падает на FK).
    created_by uuid references users(id) on delete set null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Имя уникально без учёта регистра и внешних пробелов: «РЦО» и «рцо » — одна
-- группа, иначе в списке появятся две неразличимые.
create unique index if not exists ux_dashboard_directions_name
    on dashboard_directions (organization_id, lower(btrim(name)));

alter table dashboards add column if not exists direction_id uuid
    references dashboard_directions(id) on delete set null;

create index if not exists ix_dashboards_direction
    on dashboards (organization_id, direction_id);

comment on table dashboard_directions is
    'Направления: группы дашбордов внутри раздела «Дашборды»; доступ не меняют';
comment on column dashboards.direction_id is
    'Направление дашборда (одно или никакого); удаление направления оставляет дашборд без него';

-- Журнал действий — тем же триггером, что у дашбордов и виджетов: создание,
-- переименование и удаление направления видны в «Аудите» без ручных записей.
drop trigger if exists trg_audit_dashboard_directions on dashboard_directions;
create trigger trg_audit_dashboard_directions
    after insert or update or delete on dashboard_directions
    for each row execute function fn_audit_generic('direction');
