-- 060: этап 5 по итогам ревью (08.10.2026) — «новое» считается относительно
-- того, что система УЖЕ видела, а «база» подсказки — по отчётному периоду.
--
-- 1. dataset_releases.new_fields_checked_at — выпуск просмотрен правилом
--    «новая графа». До этой правки графа считалась новой, если её не было ни
--    в одном ДРУГОМ выпуске формы; при выпуске книги по листам «другими»
--    оказывались соседние листы той же книги, и графа, появившаяся не на
--    последнем листе, не объявлялась никогда (замер на истории РЦО: при
--    недельных поставках объявилось бы 4 графы из 105, книгой целиком — 0).
--    Теперь сравниваем с выпусками, которые правило уже просмотрело: всё, что
--    принесла одна операция (книга, недельный файл с двумя датами), — одна
--    новость. Отметка ставится в той же точке сохранения, что и объявление:
--    сорвалось объявление — выпуск остаётся непросмотренным, и ежедневная
--    страховка воркера попробует снова.
--    Всё, что уже лежит в базе, помечается просмотренным: иначе первая же
--    проверка после выкладки объявила бы новостью всю историю форм.
do $$
begin
    if not exists (select 1 from information_schema.columns
                   where table_name = 'dataset_releases' and column_name = 'new_fields_checked_at') then
        alter table dataset_releases add column new_fields_checked_at timestamptz;
        update dataset_releases set new_fields_checked_at = now();
    end if;
end $$;

comment on column dataset_releases.new_fields_checked_at is
    'Когда выпуск просмотрен правилом «в форме появилась новая графа»; пусто — ещё не просмотрен';

create index if not exists ix_dataset_releases_new_fields_unchecked
    on dataset_releases (organization_id, code) where new_fields_checked_at is null;

-- 2. dashboard_form_since — отчётный период, по который форма была на
--    дашборде в момент сборки. Подсказка «новые графы» показывает то, что
--    появилось в форме ПОСЛЕ этого периода. Прежде «база» считалась по времени
--    создания выпусков и виджетов, и у этого было три изъяна:
--      • история, загруженная после сборки, становилась «новой» (у РЦО три
--        графы ФССП с январскими датами — «впервые в отчёте за 13.01», но
--        «появились после сборки»);
--      • удаление ранних виджетов сдвигало базу, и неразобранные графы молча
--        пропадали из подсказки;
--      • при переносе данных на другой сервер время создания выпусков и
--        виджетов расходится, и база вырождалась.
--    Период переживает и перевыпуск, и перенос, и удаление виджетов.
create table if not exists dashboard_form_since (
    dashboard_id uuid not null references dashboards(id) on delete cascade,
    code         text not null,
    -- Последний отчётный период формы при первом виджете на ней; пусто —
    -- дашборд собран раньше любого выпуска формы (базой станет первый выпуск).
    period       date,
    created_at   timestamptz not null default now(),
    primary key (dashboard_id, code)
);

comment on table dashboard_form_since is
    'По какой отчётный период форма была на дашборде при сборке — граница «новых граф» подсказки';

-- Формы виджета — тем же правилом, что _coverage.dataset_codes: своя форма и
-- формы рядов сравнения источников.
create or replace function fn_widget_form_codes(cfg jsonb) returns setof text
language sql immutable as $$
    select distinct x from (
        select cfg->>'dataset_code' as x
        union all
        select s->>'dataset_code' from jsonb_array_elements(
            case when jsonb_typeof(cfg->'series') = 'array' then cfg->'series' else '[]'::jsonb end) s
    ) t where x is not null and x <> ''
$$;

-- Первый виджет на форме фиксирует её период. Триггер, а не код приложения:
-- виджеты создаются десятком путей (конструктор, мастер, лестница, шаблон,
-- копия, окно новых граф), и про один из них однажды забыли бы.
create or replace function fn_widget_form_since() returns trigger language plpgsql as $$
begin
    insert into dashboard_form_since (dashboard_id, code, period)
    select new.dashboard_id, c,
           (select max(r.reporting_period_start) from dataset_releases r
             where r.organization_id = new.organization_id and r.code = c and r.status <> 'superseded')
      from fn_widget_form_codes(new.config) c
    on conflict (dashboard_id, code) do nothing;
    return new;
end $$;

drop trigger if exists trg_widget_form_since on widgets;
create trigger trg_widget_form_since after insert or update of config on widgets
    for each row execute function fn_widget_form_since();

-- Уже собранные дашборды: период — последний из выпусков, созданных к первому
-- виджету на форме (так считалась прежняя база). Если таких выпусков нет —
-- данные пришли позже виджетов (перенос на другой сервер, сборка по шаблону
-- до данных), и тогда всё, что есть сейчас, считается базой: объявлять
-- новостью форму, которую человек уже видит на дашборде, — шум.
insert into dashboard_form_since (dashboard_id, code, period)
select f.dashboard_id, f.code,
       coalesce(
           (select max(r.reporting_period_start) from dataset_releases r
             where r.organization_id = f.organization_id and r.code = f.code
               and r.created_at <= f.first_at),
           (select max(r.reporting_period_start) from dataset_releases r
             where r.organization_id = f.organization_id and r.code = f.code
               and r.status <> 'superseded'))
  from (select w.dashboard_id, w.organization_id, c as code, min(w.created_at) as first_at
          from widgets w cross join lateral fn_widget_form_codes(w.config) c
         group by 1, 2, 3) f
on conflict (dashboard_id, code) do nothing;
