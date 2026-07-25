-- 024: Row-level RLS на строки данных по подразделению (район/отдел).
--
-- Модель (opt-in на ОБЪЕКТ): строки датасетов объекта видны подразделению
-- только если для этого объекта заведены правила data_row_acl. Пока правил на
-- объект нет — строки видят все (RLS выключен для объекта). Как только появилось
-- хотя бы одно правило — непривилегированный пользователь видит ТОЛЬКО строки
-- (row_label), выданные его подразделению (whitelist). Привилегированные роли
-- (admin/moderator/senior_moderator) и предпросмотр конструктора видят все строки.
--
-- Применяется к ВИДЖЕТНЫМ чтениям датасета (таблица, серии по строкам, сравнение,
-- heatmap, pivot, динамика) и к drill-до-первичных-строк. Именованные МЕТРИКИ
-- (формульный движок) НЕ фильтруются — их значения остаются объективными
-- (организационными); row-RLS — это видимость строк в виджетах.
--
-- Идемпотентно.

create table if not exists data_row_acl (
    id uuid primary key default gen_random_uuid(),
    object_id uuid not null references objects(id) on delete cascade,
    department_id uuid not null references departments(id) on delete cascade,
    row_label text not null,             -- разрешённая строка (row_label) датасетов объекта
    created_by uuid references users(id),
    created_at timestamptz not null default now(),
    unique (object_id, department_id, row_label)
);

-- Быстрая выборка «что разрешено подразделению в объекте» и «включён ли RLS у объекта».
create index if not exists ix_data_row_acl_object on data_row_acl (object_id, department_id);
