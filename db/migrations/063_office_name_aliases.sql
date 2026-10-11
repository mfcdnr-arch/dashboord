-- =========================================================
-- 063 · Эталонные названия отделений: запомненные соответствия
--
-- Одно и то же отделение разные формы пишут по-разному: ежедневный отчёт и
-- «окна» — «Отделение № 3 ГБУ "МФЦ ДНР" г. Донецк пр-т Ильича, 63 а», форма
-- «Время» — «Отделение МФЦ № 3 г. Донецк», ведомства — «Отделение №3 ГБУ «МФЦ
-- ДНР» г. Донецк, пр-кт Ильича, 63а». Для системы это три разных строки:
-- формы не сопоставляются между собой и не попадают на карту.
--
-- Эталон — строка, связанная с отделением в справочнике
-- (mfc_offices.row_label). Здесь хранится, какой вариант какому отделению
-- соответствует; при выпуске вариант подменяется эталоном сам.
--
-- Статусы:
--   confirmed — человек подтвердил: вариант → отделение;
--   ignored   — «это не отделение» (итоговая строка, точка), больше не спрашивать;
--   pending   — система заметила незнакомое название и уже сообщила о нём
--               (антидубль уведомлений), решения ещё нет.
--
-- Идемпотентно.
-- =========================================================

create table if not exists office_name_aliases (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    label text not null,                 -- вариант, как он пришёл в форме
    label_key text not null,             -- нормализованный (регистр, ё, пробелы)
    status text not null check (status in ('confirmed', 'ignored', 'pending')),
    -- Отделение, которому соответствует вариант. Удалили отделение — уходит и
    -- соответствие: подменять больше не на что.
    office_id uuid references mfc_offices(id) on delete cascade,
    suggested_office_id uuid references mfc_offices(id) on delete set null,
    seen_code text,                      -- в какой форме вариант встретился впервые
    notified_at timestamptz,
    decided_by uuid references users(id),
    decided_at timestamptz,
    created_at timestamptz not null default now(),
    unique (organization_id, label_key),
    check (status <> 'confirmed' or office_id is not null)
);

create index if not exists ix_office_name_aliases_org on office_name_aliases (organization_id, status);
