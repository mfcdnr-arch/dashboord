-- Подборка «Руководителю»: какие дашборды попадают в раздел для руководства.
--
-- Отдельной сущности не заводим сознательно: КТО что видит, уже решают гранты
-- (access_grants), и вторая система прав рядом с ними означала бы два источника
-- правды. Флаг отвечает только на вопрос «показывать ли дашборд в подборке»,
-- а доступ к нему остаётся там же, где у всех остальных.
alter table dashboards add column if not exists featured boolean not null default false;

-- Порядок в подборке задаёт администратор: руководителю важно, что первым
-- окажется главный отчёт, а не тот, который завели раньше.
alter table dashboards add column if not exists featured_order integer not null default 0;

create index if not exists ix_dashboards_featured
    on dashboards (organization_id, featured_order, name) where featured;
