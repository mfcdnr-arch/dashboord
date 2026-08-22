-- Отчётная дата страницы-СРЕЗА.
--
-- Срез — страница, закреплённая за конкретным отчётом: у её виджетов задан
-- config.period, и приход новой недели их не меняет. Мастер называет такие
-- страницы «Отчёт за ДД.ММ.ГГГГ», и до сих пор интерфейс опознавал их ПО ИМЕНИ.
-- Признак по имени ненадёжен: стоит человеку переименовать страницу, и она
-- перестаёт быть срезом для интерфейса, оставаясь им по сути.
alter table dashboard_pages
    add column if not exists period date;

comment on column dashboard_pages.period is
    'Отчётная дата страницы-среза (виджеты закреплены за ней); null — сводная страница';

-- Перенос уже существующих страниц: дату берём из самих виджетов. Страница —
-- срез, если у неё есть виджеты и У ВСЕХ задана ОДНА И ТА ЖЕ дата. Одного
-- закреплённого виджета среди свободных мало: это не срез, а один снимок на
-- сводной странице.
update dashboard_pages p
   set period = sub.period
  from (
        select w.page_id,
               min((w.config->>'period')::date) as period
          from widgets w
         group by w.page_id
        having count(*) = count(w.config->>'period')
           and count(distinct w.config->>'period') = 1
       ) sub
 where p.id = sub.page_id
   and p.period is null;
