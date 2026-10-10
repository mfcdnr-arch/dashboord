-- 061: шаблон разметки — на ФОРМУ, а не на объект (09.10.2026) + вердикт сверки
-- по листу + графа-название строки у выпуска.
--
-- Почему. Недельная книга «Отчёт МФЦ для Минэкономразвития» — это ОДИН объект и
-- ЧЕТЫРЕ формы на разных листах (Показатели, Проблемные вопросы, Итоги недели,
-- Планы на неделю), у каждой свой код набора. Шаблон же был один на объект
-- (PK object_id): каждый выпуск листа затирал разметку соседнего, и следующая
-- книга узнавалась только по ПОСЛЕДНЕМУ выпущенному листу. Ряд формы и так
-- держится на коде (`assert_code_free`, `uq_dataset_releases_active`), поэтому
-- естественный ключ шаблона — (объект, код набора). Имя листа — подсказка для
-- выбора таблицы, а не ключ: у годовой книги РЦО 201 лист — это ОДНА форма за
-- разные даты, и ключ по листу её бы раздробил.

-- 1. object_layout_templates: PK (object_id, dataset_code), имя листа.
do $$
begin
    -- Код формы восстанавливаем из выпуска, с которого снята разметка.
    update object_layout_templates t set dataset_code = r.code
      from dataset_releases r
     where t.dataset_code is null and r.id = t.source_release_id;
    -- Шаблон без кода к форме не привязать: убираем его в историю, а не теряем.
    insert into object_layout_template_history(object_id, fingerprint, mode, layout, fields, cells,
           row_count, dataset_code, source_release_id, headers, levels, valid_from, replaced_reason)
    select object_id, fingerprint, mode, layout, fields, cells, row_count, dataset_code,
           source_release_id, headers, levels, updated_at,
           'код формы не восстановлен при переходе на шаблоны по формам'
      from object_layout_templates where dataset_code is null;
    delete from object_layout_templates where dataset_code is null;

    if exists (select 1 from pg_constraint
                where conrelid = 'object_layout_templates'::regclass and contype = 'p'
                  and conname = 'object_layout_templates_pkey'
                  and array_length(conkey, 1) = 1) then
        alter table object_layout_templates drop constraint object_layout_templates_pkey;
    end if;
    alter table object_layout_templates alter column dataset_code set not null;
    if not exists (select 1 from pg_constraint
                    where conrelid = 'object_layout_templates'::regclass and contype = 'p') then
        alter table object_layout_templates add primary key (object_id, dataset_code);
    end if;
end $$;

alter table object_layout_templates add column if not exists sheet_name text;
alter table object_layout_template_history add column if not exists sheet_name text;

create index if not exists ix_layout_template_history_form
    on object_layout_template_history (object_id, dataset_code, replaced_at desc);

comment on table object_layout_templates is
    'Разметка формы (объект + код набора) из её последнего выпуска — подставляется, '
    'когда приходит файл той же структуры. У книги из нескольких форм — шаблон на каждую';
comment on column object_layout_templates.sheet_name is
    'Лист книги, с которого снята разметка: подсказка при выборе таблицы, не ключ';

-- 2. Вердикт сверки — по ЛИСТУ. Раньше он был один на задание
--    (`extraction_jobs.template_match`), и книга из четырёх форм не могла
--    сказать «узнаны все четыре» или «лист «Итоги недели» изменился».
--    Сводка по книге остаётся в задании.
alter table extracted_tables add column if not exists template_code text;
alter table extracted_tables add column if not exists template_match text;
alter table extracted_tables add column if not exists template_note text;

comment on column extracted_tables.template_code is
    'Форма (код набора), чей шаблон совпал с этим листом; пусто — лист в шаблонах не значится';

-- 3. Графа-название строки — у ВЫПУСКА. Признак `canonical_fields.is_row_label`
--    живёт на уровне объекта и перезаписывается каждым выпуском: у объекта
--    Минэкономразвития таких граф три (по одной на лист), и графа, которая на
--    одном листе — название строки, а на другом — значение, переключала бы его
--    каждую неделю. Таблице нужно знать, чем подписаны строки ИМЕННО этого
--    выпуска («Краткая характеристика», а не безликое «Строка»).
alter table dataset_release_fields add column if not exists is_row_label boolean not null default false;
create unique index if not exists uq_release_fields_row_label
    on dataset_release_fields (dataset_release_id) where is_row_label;

-- Перенос для уже выпущенных данных.
-- (а) Объявленная графа выпуска, помеченная названием в справочнике объекта и
--     без единого значения в этом выпуске (значения названия уходят в
--     row_label, а не в графу). У выпуска без значений вовсе (пустой лист)
--     хватает флага справочника. Ставим, только если такая графа ровно одна.
with cand as (
    select rf.id, rf.dataset_release_id
      from dataset_release_fields rf
      join dataset_releases r on r.id = rf.dataset_release_id
      join canonical_fields cf on cf.object_id = r.object_id and cf.code = rf.canonical_field_code
     where cf.is_row_label
       and not exists (select 1 from dataset_values v
                        where v.dataset_release_id = rf.dataset_release_id
                          and v.canonical_field_code = rf.canonical_field_code)
), one as (
    select dataset_release_id from cand group by dataset_release_id having count(*) = 1
)
update dataset_release_fields rf set is_row_label = true
  from cand c join one o on o.dataset_release_id = c.dataset_release_id
 where rf.id = c.id
   and not exists (select 1 from dataset_release_fields x
                    where x.dataset_release_id = rf.dataset_release_id and x.is_row_label);

-- (б) Выпуск, у которого название не объявлено вовсе (недельные файлы
--     ведомств грузил скрипт, объявлявший графы только по значениям), получает
--     графу-название из шаблона своей формы — если она есть в справочнике
--     объекта и у неё нет значений в этом выпуске.
insert into dataset_release_fields(dataset_release_id, canonical_field_code, extracted_column_id, is_row_label)
select r.id, f.code, null, true
  from dataset_releases r
  join object_layout_templates t on t.object_id = r.object_id and t.dataset_code = r.code
  cross join lateral (
      select e->>'field_code' as code from jsonb_array_elements(t.fields) e
       where coalesce((e->>'is_row_label')::boolean, false) limit 1) f
 where f.code is not null
   and exists (select 1 from canonical_fields cf where cf.object_id = r.object_id and cf.code = f.code)
   and not exists (select 1 from dataset_release_fields x
                    where x.dataset_release_id = r.id and (x.is_row_label or x.canonical_field_code = f.code))
   and not exists (select 1 from dataset_values v
                    where v.dataset_release_id = r.id and v.canonical_field_code = f.code);

comment on column dataset_release_fields.is_row_label is
    'Графа, из которой взяты названия строк этого выпуска (не больше одной на выпуск)';
