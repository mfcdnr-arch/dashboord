-- =========================================================
-- 010 · Датасеты: канонические поля + значения
-- Этап 3.2. Решения проекта:
--   * канонические поля — ЛОКАЛЬНЫЕ, справочник на уровне ОБЪЕКТА
--     (переиспользуются между папками объекта; row-level отложен);
--   * значения датасета хранятся «в длину»: строка = НАЗВАНИЕ СТРОКИ (row_label)
--     + канон. поле → типизированное значение (док-06: ячейка = имя строки + столбец).
-- =========================================================

-- Справочник канонических полей объекта (куда маппятся распознанные столбцы).
create table if not exists canonical_fields (
    id uuid primary key default gen_random_uuid(),
    object_id uuid not null references objects(id) on delete cascade,
    code text not null,                       -- машинный код поля (slug)
    name text not null,                       -- отображаемое имя
    data_type text not null default 'text',   -- number | date | text
    unit text,                                -- ед. измерения (шт., руб., % …)
    is_row_label boolean not null default false,  -- поле-метка строки (не значение)
    description text,
    created_by uuid references users(id),
    created_at timestamptz not null default now(),
    unique (object_id, code)
);

create index if not exists ix_canonical_fields_object on canonical_fields (object_id);

-- Привязка выпуска к объекту (для листинга датасетов в разрезе объекта).
alter table dataset_releases
    add column if not exists object_id uuid references objects(id) on delete set null;

create index if not exists ix_dataset_releases_object on dataset_releases (object_id);

-- Значения датасета (материализуются при подтверждении выпуска).
create table if not exists dataset_values (
    id uuid primary key default gen_random_uuid(),
    dataset_release_id uuid not null references dataset_releases(id) on delete cascade,
    row_index integer not null,               -- порядок строки в источнике
    row_label text,                           -- название строки (из столбца-метки)
    canonical_field_code text not null,       -- какое канон. поле
    value_text text,
    value_number numeric,
    value_date date,
    created_at timestamptz not null default now()
);

create index if not exists ix_dataset_values_release on dataset_values (dataset_release_id);
create index if not exists ix_dataset_values_field
    on dataset_values (dataset_release_id, canonical_field_code);
