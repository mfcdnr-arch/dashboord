-- 037. Шаблон разметки объекта: как размечали эту форму в прошлый раз.
--
-- Недельные формы одного объекта — это ОДИН И ТОТ ЖЕ бланк за разные даты, но
-- разметка (область данных, этажи шапки, столбец названий, выбранные графы,
-- исключённые строки-заготовки) нигде не сохранялась: она доезжала до
-- build_release аргументом и растворялась. Человек размечал одну и ту же форму
-- заново каждую неделю.
--
-- `fingerprint` — отпечаток СТРУКТУРЫ формы (состав и порядок заголовков,
-- этажи шапки, ориентация). Нужен, чтобы отличить «та же форма за новую
-- неделю» от «форма изменилась»: имена файлов и контрольные суммы для этого не
-- годятся — они разные при одном бланке. Не совпал — шаблон не подставляем,
-- человек размечает руками, иначе получим тихо неверные цифры на дашборде.
--
-- Один шаблон на объект: объект = одна форма (решение заказчика). Новый выпуск
-- перезаписывает шаблон — актуальна последняя разметка.

create table if not exists object_layout_templates (
    object_id         uuid primary key references objects(id) on delete cascade,
    fingerprint       text not null,
    mode              text not null default 'table',   -- table | cells
    layout            jsonb not null default '{}'::jsonb,   -- data_rect/header_rows/orientation/skip_rows
    fields            jsonb not null default '[]'::jsonb,   -- выбранные показатели с именами и типами
    cells             jsonb not null default '[]'::jsonb,   -- режим отдельных ячеек
    row_count         integer,                              -- строк данных на момент выпуска
    dataset_code      text,
    source_release_id uuid references dataset_releases(id) on delete set null,
    updated_by        uuid references users(id),
    updated_at        timestamptz not null default now()
);

comment on table object_layout_templates is
    'Разметка формы объекта из последнего выпуска — подставляется при загрузке следующего файла той же структуры';
