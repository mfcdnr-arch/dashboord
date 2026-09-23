-- История шаблонов разметки объекта: прежний шаблон не теряется при замене.
--
-- Шаблон один на объект (`object_layout_templates`, PK = object_id), и выпуск
-- переписывал его молча. 22.09.2026 на боевом ошибочный выпуск перечня услуг
-- заменил разметку формы МАХ своей, и следующий файл МАХ перестал бы
-- узнаваться сам; восстанавливать пришлось по последнему выпуску, а исключённые
-- строки бланка вернуть было неоткуда. Теперь каждая замена кладёт прежний
-- шаблон сюда, и вернуть его можно одной кнопкой на экране объекта.
create table if not exists object_layout_template_history (
    id                uuid primary key default gen_random_uuid(),
    object_id         uuid not null references objects(id) on delete cascade,
    fingerprint       text not null,
    mode              text not null default 'table',
    layout            jsonb not null default '{}'::jsonb,
    fields            jsonb not null default '[]'::jsonb,
    cells             jsonb not null default '[]'::jsonb,
    row_count         integer,
    dataset_code      text,
    source_release_id uuid,
    headers           jsonb not null default '[]'::jsonb,
    levels            jsonb not null default '{}'::jsonb,
    -- Когда этот шаблон действовал и кто его сменил.
    valid_from        timestamptz,
    replaced_at       timestamptz not null default now(),
    replaced_by       uuid references users(id) on delete set null,
    replaced_reason   text
);

create index if not exists ix_layout_template_history_object
    on object_layout_template_history (object_id, replaced_at desc);
