-- =========================================================
-- 052 · Справочник отделений МФЦ (раздел «Карта»)
--
-- До сих пор отделение существовало в системе ТОЛЬКО строкой данных
-- (dataset_values.row_label), которая приходит из загруженного отчёта и через
-- интерфейс не правится. Ни адреса, ни телефона, ни режима работы система не
-- хранила нигде — а именно они нужны карте отделений.
--
-- Ключ справочника — ИМЯ отделения, а не внешний id: в присланном шаблоне
-- (62 строки) имена уникальны, а `id` ДУБЛИРУЕТСЯ — у ТОСП стоит id головного
-- МФЦ (проверено: 9 пар). Внешний id храним как справочный, без уникальности.
--
-- Идемпотентно.
-- =========================================================

create table if not exists mfc_offices (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,

    -- Сведения, которые видит человек на точке карты
    name text not null,                 -- «МФЦ №1 по городу Донецк»
    address text,                       -- «г. Донецк, ул. Челюскинцев, 167»
    city text,                          -- населённый пункт (для поиска и группировки)
    phone text,
    phone2 text,
    email text,
    website text,
    -- Режим работы по дням: {"mon":{"from":"08:00","to":"17:00"}, "sun":null, ...}
    -- Отсутствие ключа или null = выходной. В шаблоне он приходит одной строкой
    -- («пн: 08:00 - 17:00,  вт: …») и разбирается при импорте.
    hours jsonb not null default '{}'::jsonb,
    note text,                          -- примечание (обед, особые дни)

    -- Место на карте. Держим раздельно, а не парой в тексте: по ним считается
    -- попадание в контур и рисуется точка.
    lat double precision,
    lon double precision,

    -- Связка со строкой отчёта: в данных РЦО адрес записан иначе, чем в
    -- справочнике, поэтому сопоставляется человеком один раз на отделение.
    row_label text,

    -- Закрытое отделение НЕ удаляем: цифры за прошлые периоды по нему остаются.
    is_active boolean not null default true,

    source_id text,                     -- внешний id из шаблона (справочно, НЕ уникален)
    created_by uuid references users(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    unique (organization_id, name)
);

create index if not exists ix_mfc_offices_org on mfc_offices (organization_id, is_active, name);

-- Одна строка отчёта не может принадлежать двум отделениям — иначе нагрузка
-- показалась бы дважды и в разных местах карты.
create unique index if not exists uq_mfc_offices_row_label
    on mfc_offices (organization_id, row_label) where row_label is not null;
